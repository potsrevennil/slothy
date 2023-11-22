#
# Copyright (c) 2022 Arm Limited
# Copyright (c) 2022 Hanno Becker
# Copyright (c) 2023 Amin Abdulrahman, Matthias Kannwischer
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Author: Hanno Becker <hannobecker@posteo.de>
#

import re
import subprocess
import logging

class NestedPrint():
    """Helper for recursive printing of structures"""
    def __str__(self):
        top = [ self.__class__.__name__ + ":" ]
        res = []
        indent = ' ' * 8
        for name, value in vars(self).items():
            res += f"{name}: {value}".splitlines()
        res = top + [ indent + r for r in res ]
        return '\n'.join(res)
    def log(self, fun):
        """Pass self-description line-by-line to logging function"""
        for l in str(self).splitlines():
            fun(l)

class LockAttributes(object):
    """Base class adding support for 'locking' the set of attributes, that is,
       preventing the creation of any further attributes. Note that the modification
       of already existing attributes remains possible.

       Our primary use case is for configurations, where this class is used to catch typos
       in the user configuration."""
    def __init__(self):
        self.__dict__["_locked"] = False
        self._locked = False
    def lock(self):
        """Lock set of attributes"""
        self._locked = True
    def __setattr__(self, attr, val):
        if self._locked and attr not in dir(self):
            varlist = [v for v in dir(self) if not v.startswith("_") ]
            varlist = '\n'.join(map(lambda x: '* ' + x, varlist))
            raise TypeError(f"Unknown attribute {attr}. \nValid attributes are:\n{varlist}")
        elif self._locked and attr == "_locked":
            raise TypeError("Can't unlock an object")
        object.__setattr__(self,attr,val)

class AsmHelperException(Exception):
    """An exception encountered during an assembly helper"""

class AsmHelper():
    """Some helper functions for dealing with assembly"""

    @staticmethod
    def find_indentation(source):
        """Attempts to find the prevailing indentation in a piece of assembly"""

        def get_indentation(l):
            return len(l) - len(l.lstrip())

        # Remove empty lines
        source = list(filter(lambda t: t.strip() != "", source))
        l = len(source)

        if l == 0:
            return None

        indentations = list(map(get_indentation, source))

        # Some labels may use a different indentation -- here, we just check if
        # there's a dominant indentation
        top_start = (3 * l) // 4
        indentations.sort()
        indentations = indentations[top_start:]

        if indentations[0] == indentations[-1]:
            return indentations[0]

        return None

    @staticmethod
    def apply_indentation(source, indentation):
        """Apply consistent indentation to assembly source"""
        if indentation is None:
            return source
        assert isinstance(indentation, int)
        indent = ' ' * indentation
        return [ indent + l.lstrip() for l in source ]

    @staticmethod
    def rename_function(source, old_funcname, new_funcname):
        """Rename function in assembly snippet"""

        # For now, just replace function names line by line
        def change_funcname(s):
            s = re.sub( f"{old_funcname}:", f"{new_funcname}:", s)
            s = re.sub( f"\\.global(\\s+){old_funcname}", f".global\\1{new_funcname}", s)
            s = re.sub( f"\\.type(\\s+){old_funcname}", f".type\\1{new_funcname}", s)
            return s
        return '\n'.join([ change_funcname(s) for s in source.splitlines() ])

    @staticmethod
    def split_semicolons(body):
        """Split assembly snippet across semicolons`"""
        return [ l for s in body for l in s.split(';') ]

    @staticmethod
    def reduce_source_line(line):
        """Simplify or ignore assembly source line"""
        regexp_align_txt = r"^\s*\.(?:p2)?align"
        regexp_req_txt   = r"\s*(?P<alias>\w+)\s+\.req\s+(?P<reg>\w+)"
        regexp_unreq_txt = r"\s*\.unreq\s+(?P<alias>\w+)"
        regexp_label_txt = r"\s*(?P<label>\w+)\s*:\s*$"
        regexp_align = re.compile(regexp_align_txt)
        regexp_req   = re.compile(regexp_req_txt)
        regexp_unreq = re.compile(regexp_unreq_txt)
        regexp_label = re.compile(regexp_label_txt)

        def strip_comment(s):
            s = s.split("//")[0]
            s = re.sub("/\\*[^*]*\\*/","",s)
            return s.strip()
        def is_empty(s):
            return s == ""
        def is_asm_directive(s):
            # We only accept (and ignore) .req and .unreqs in code so far
            return sum([ regexp_req.match(s)   is not None,
                         regexp_unreq.match(s) is not None,
                         regexp_align.match(s) is not None]) > 0

        def is_label(s):
            return (regexp_label.match(s) is not None)

        line = strip_comment(line)
        if is_empty(line):
            return
        if is_asm_directive(line):
            return
        if is_label(line):
            return
        return line

    @staticmethod
    def reduce_source(src, allow_nops=True):
        """Simplify assembly snippet"""
        if isinstance(src,str):
            src = src.splitlines()
        def filter_nop(src):
            if allow_nops:
                return True
            return src != "nop"
        src = map(AsmHelper.reduce_source_line, src)
        src = filter(lambda x: x != None, src)
        src = filter(filter_nop, src)
        src = list(src)
        return src

    @staticmethod
    def extract(source, lbl_start=None, lbl_end=None):
        """Extract code between two labels from an assembly source"""
        pre, body, post = AsmHelper._extract_core(source, lbl_start, lbl_end)
        body = AsmHelper.reduce_source(body, allow_nops=False)
        return pre, body, post

    @staticmethod
    def _extract_core(source, lbl_start=None, lbl_end=None):
        pre  = []
        body = []
        post = []

        lines = iter(source.splitlines())
        source = source.splitlines()
        if lbl_start is None and lbl_end is None:
            body = source
            return pre, body, post

        loop_lbl_regexp_txt = r"^\s*(?P<label>\w+)\s*:(?P<remainder>.*)$"
        loop_lbl_regexp = re.compile(loop_lbl_regexp_txt)
        l = None
        keep = False
        state = 0 # 0: haven't found initial label yet, 1: between labels, 2: after snd label

        # If no start label is provided, scan from the start to the end label
        if lbl_start is None:
            state = 1

        idx=0
        while True:
            idx += 1
            if not keep:
                l = next(lines, None)
            if l is None:
                break
            keep = False
            if state == 2:
                post.append(l)
                continue
            expect_label = [ lbl_start, lbl_end ][state]
            cur_buf = [ pre, body ][state]
            p = loop_lbl_regexp.match(l)
            if p is not None and p.group("label") == expect_label:
                l = p.group("remainder")
                keep = True
                state += 1
                continue
            cur_buf.append(l)
            continue

        if state < 2:
            if lbl_start is not None and lbl_end is not None:
                raise AsmHelperException(f"Failed to identify region {lbl_start}-{lbl_end}")
            if state == 0:
                if lbl_start is not None:
                    lbl = lbl_start
                else:
                    lbl = lbl_end
                raise AsmHelperException(f"Couldn't find label {lbl}")

        return pre, body, post

class AsmAllocation():
    """Helper for tracking register aliases via .req and .unreq"""

    def __init__(self):
        self.allocations = {}
        self.regexp_req_txt   = r"\s*(?P<alias>\w+)\s+\.req\s+(?P<reg>\w+)"
        self.regexp_unreq_txt = r"\s*\.unreq\s+(?P<alias>\w+)"
        self.regexp_req   = re.compile(self.regexp_req_txt)
        self.regexp_unreq = re.compile(self.regexp_unreq_txt)

    def _add_allocation(self, alias, reg):
        if alias in self.allocations:
            raise AsmHelperException(f"Double definition of alias {alias}")
        if reg in self.allocations:
            reg_name = self.allocations[reg]
        else:
            reg_name = reg
        self.allocations[alias] = reg_name

    def _remove_allocation(self, alias):
        if not alias in self.allocations:
            raise AsmHelperException(f"Couldn't find alias {alias} --"
                                     " .unreq without .req in your source?")
        del self.allocations[alias]

    def parse_line(self, line):
        """Check if an assembly line is a .req or .unreq directive, and update the
        alias dictionary accordingly. Otherwise, do nothing."""
        # Check if it's an allocation
        p = self.regexp_req.match(line)
        if p is not None:
            alias = p.group("alias")
            reg = p.group("reg")
            self._add_allocation(alias,reg)
            return

        # Regular expression for a definition removal
        p = self.regexp_unreq.match(line)
        if p is not None:
            alias = p.group("alias")
            self._remove_allocation(alias)
            return

        # We ignore everything else

    def parse(self, src):
        """Build register alias dictionary from assembly source"""
        for s in src:
            self.parse_line(s)

    @staticmethod
    def parse_allocs(src):
        """"Parse register aliases in assembly source into AsmAllocation object."""
        allocs = AsmAllocation()
        allocs.parse(src)
        return allocs.allocations

    @staticmethod
    def unfold_all_aliases(aliases, src):
        """Unfold aliases in assembly source"""
        def _apply_single_alias_to_line(alias_from, alias_to, src):
            return re.sub(f"(\\W){alias_from}(\\W|\\Z)", f"\\1{alias_to}\\2", src)
        def _apply_multiple_aliases_to_line(line):
            for (alias_from, alias_to) in aliases.items():
                line = _apply_single_alias_to_line(alias_from, alias_to, line)
            return line
        res = []
        for l in src:
            res.append(_apply_multiple_aliases_to_line(l))
        return res

class BinarySearchLimitException(Exception):
    """Binary search has exceeded its limit without finding a solution"""

def binary_search(func, threshold=256, minimum=-1, start=0, precision=1,
                  timeout_below_precision=None):
    """Conduct a binary search"""
    start = max(start,minimum)
    last_failure = minimum
    val = start
    # Find _some_ version that works
    while True:
        if val > threshold:
            raise BinarySearchLimitException
        def double_val(val):
            if val == 0:
                return 1
            return 2*val
        success, result = func(val)
        if success:
            last_success = val
            last_success_core = result
            break
        last_failure = val
        val = double_val(val)
    # Find _first_ version that works
    while last_success - last_failure > 1:
        timeout = None
        if last_success - last_failure <= precision:
            if timeout_below_precision is None:
                break
            timeout = timeout_below_precision
        val = last_failure + ( last_success - last_failure ) // 2
        success, result = func(val, timeout=timeout)
        if success:
            last_success = val
            last_success_core = result
        else:
            last_failure = val
    return last_success, last_success_core

class AsmMacro():
    """Helper class for parsing and applying assembly macros"""

    def __init__(self, name, args, body):
        self.name = name
        self.args = args
        self.body = body

    def __call__(self,args_dict):
        output = []
        for l in self.body:
            for arg in self.args:
                l = re.sub(f"\\\\{arg}(\\W|$)",args_dict[arg] + "\\1",l)
            l = re.sub("\\\\\\(\\)","",l)
            output.append(l)
        return output

    def __repr__(self):
        return self.name

    def unfold_in(self, source, change_callback=None):
        """Unfold all applications of macro in assembly source"""
        macro_regexp_txt = rf"^\s*{self.name}"
        arg_regexps = []
        if self.args == [""]:
            while True:
                continue

        if len(self.args) > 0:
            macro_regexp_txt = macro_regexp_txt + "\\s+"

        for arg in self.args:
            arg_regexps.append(rf"\s*(?P<{arg}>[^,]+)\s*")

        macro_regexp_txt += ','.join(arg_regexps)
        macro_regexp = re.compile(macro_regexp_txt)

        output = []

        indentation_regexp_txt = r"^(?P<whitespace>\s*)($|\S)"
        indentation_regexp = re.compile(indentation_regexp_txt)

        # Go through source line by line and check if there's a macro invocation
        for l in AsmHelper.reduce_source(source):

            lp = AsmHelper.reduce_source_line(l)
            if lp is not None:
                p = macro_regexp.match(lp)
            else:
                p = None

            if p is None:
                output.append(l)
                continue
            if change_callback:
                change_callback()
            # Try to keep indentation
            indentation = indentation_regexp.match(l).group("whitespace")
            repl = [ indentation + s.strip() for s in self(p.groupdict())]
            output += repl

        return output

    @staticmethod
    def unfold_all_macros(macros, source):
        """Unfold list of macros in assembly source"""

        def list_of_instances(l,c):
            return isinstance(l,list) and all(map(lambda m: isinstance(m,c), l))
        def dict_of_instances(l,c):
            return isinstance(l,dict) and list_of_instances(list(l.values()), c)
        if isinstance(macros,str):
            macros = macros.splitlines()
        if list_of_instances(macros, str):
            macros = AsmMacro.extract(macros)
        if not dict_of_instances(macros, AsmMacro):
            raise AsmHelperException(f"Invalid argument: {macros}")

        change = True
        while change:
            change = False
            def cb():
                nonlocal change
                change = True
            for m in macros.values():
                source = m.unfold_in(source, change_callback=cb)
        return source

    @staticmethod
    def extract(source):
        """Parse all macro definitions in assembly source file"""

        macros = {}

        state = 0 # 0: Not in a macro 1: In a macro
        current_macro = None
        current_args = None
        current_body = None

        macro_start_regexp_txt = r"^\s*\.macro\s+(?P<name>\w+)(?P<args>.*)$"
        macro_start_regexp = re.compile(macro_start_regexp_txt)

        slothy_no_unfold_regexp_txt = r".*//\s*slothy:\s*no-unfold\s*$"
        slothy_no_unfold_regexp = re.compile(slothy_no_unfold_regexp_txt)

        macro_end_regexp_txt = r"^\s*\.endm\s*$"
        macro_end_regexp = re.compile(macro_end_regexp_txt)

        for cur in source:

            if state == 0:

                p = macro_start_regexp.match(cur)
                if p is None:
                    continue

                # Ignore macros with "// slothy:no-unfold" annotation
                if slothy_no_unfold_regexp.match(cur) is not None:
                    continue

                current_args = [ a.strip() for a in p.group("args").split(',') ]
                current_macro = p.group("name")
                current_body = []

                if current_args == ['']:
                    current_args = []

                state = 1
                continue

            if state == 1:
                p = macro_end_regexp.match(cur)
                if p is None:
                    current_body.append(cur)
                    continue

                macros[current_macro] = AsmMacro(current_macro, current_args, current_body)

                current_macro = None
                current_body = None
                current_args = None

                state = 0
                continue

        return macros

    @staticmethod
    def extract_from_file(filename):
        """Parse all macro definitions in assembly file"""
        f = open(filename,"r")
        return AsmMacro.extract(f.read().splitlines())

class CPreprocessor():
    """Helper class for the application of the C preprocessor"""

    magic_string = "SLOTHY_PREPROCESSED_REGION"

    @staticmethod
    def unfold(header, body, gcc):
        """Runs the concatenation of header and body through the preprocessor"""
        code = header + [CPreprocessor.magic_string] + body

        r = subprocess.run([gcc, "-E", "-x", "assembler-with-cpp","-"],
                           input='\n'.join(code), text=True, capture_output=True, check=True)

        unfolded_code = r.stdout.split('\n')
        magic_idx = unfolded_code.index(CPreprocessor.magic_string)
        unfolded_code = unfolded_code[magic_idx+1:]

        return unfolded_code

class Permutation():
    """Helper class for manipulating permutations"""

    @staticmethod
    def is_permutation(perm, sz):
        """Checks whether dictionary perm is a permutation of size sz."""
        err = False
        k = list(perm.keys())
        k.sort()
        v = list(perm.values())
        v.sort()
        if k != list(range(sz)):
            err = True
        if v != list(range(sz)):
            err = True
        if err:
            print(f"Keys:   {k}")
            print(f"Values: {v}")
        return err is False

    @staticmethod
    def permutation_id(sz):
        """Return the identity permutation of size sz."""
        return { i:i for i in range(sz) }

    @staticmethod
    def permutation_comp(p_b, p_a):
        """Compose two permutations.
        
        This computes 'p_b o p_a', that is, 'p_a first, then p_b'."""
        l_a = len(p_a.values())
        l_b = len(p_b.values())
        assert l_a == l_b
        return { i:p_b[p_a[i]] for i in range(l_a) }

    @staticmethod
    def permutation_pad(perm,pre,post):
        """Pad permutation with identity permutation at front and back"""
        s = len(perm.values())
        r = {}
        r = r | { pre + i : pre + j for (i,j) in perm.items() if isinstance(i, int) }
        r = r | { i:i for i in range(pre) }
        r = r | { i:i for i in map(lambda i: i + s + pre, range(post)) }
        return r

    @staticmethod
    def permutation_move_entry_forward(l, idx_from, idx_to):
        """Create transposition permutation"""
        assert idx_to <= idx_from
        res = {}
        res = res | { i:i for i in range(idx_to) }
        res = res | { i:i+1 for i in range(idx_to,  idx_from) }
        res = res | { idx_from : idx_to }
        res = res | { i:i for i in range (idx_from + 1, l) }
        return res

    @staticmethod
    def iter_swaps(p, n):
        """Iterate over all inputs that have their order reversed by
        the permutation."""
        return ((i,j,p[i],p[j]) for i in range(n) for j in range(n) \
            if i < j and p[j] < p[i])


class DeferHandler(logging.Handler):
    """Handler collecting all records produced by a logger and relaying
    them to the same or different logger later."""
    def __init__(self):
        super().__init__()
        self._records = []
    def emit(self, record):
        self._records.append(record)
    def forward(self, logger):
        """Send all captured records to the given logger"""
        for r in self._records:
            logger.handle(r)
        self._records = []
