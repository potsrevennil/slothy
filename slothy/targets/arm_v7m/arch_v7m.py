import logging
import inspect
import re
import math
from enum import Enum
from functools import cache

from sympy import simplify

llvm_mca_arch = "arm"  # TODO


class RegisterType(Enum):
    GPR = 1
    FPR = 2
    STACK_FPR = 3
    STACK_GPR = 4
    FLAGS = 5
    HINT = 6

    def __str__(self):
        return self.name
    def __repr__(self):
        return self.name

    @cache
    @staticmethod
    def list_registers(reg_type, only_extra=False, only_normal=False, with_variants=False):
        """Return the list of all registers of a given type"""

        stack_locations  = [ f"STACK{i}"  for i in range(8) ]
        fpstack_locations  = [ f"STACK{i}"  for i in range(8) ]

        gprs_normal  = [ f"r{i}" for i in range(15) if i is not 13 ]
        fprs_normal  = [ f"s{i}" for i in range(31) ]

        gprs_extra  = []
        fprs_extra  = []

        gprs  = []
        fprs  = []
        # TODO: What are hints?
        hints = [ f"t{i}" for i in range(100) ] + \
                [ f"t{i}{j}" for i in range(8) for j in range(8) ] + \
                [ f"t{i}_{j}" for i in range(16) for j in range(16) ]

        flags = ["flags"]
        if not only_extra:
            gprs  += gprs_normal
            fprs += fprs_normal
        if not only_normal:
            gprs  += gprs_extra
            fprs += fprs_extra

        return { RegisterType.GPR       : gprs,
                 RegisterType.STACK_GPR : stack_locations,
                 RegisterType.FPR       : fprs,
                 RegisterType.STACK_FPR : fpstack_locations,
                 RegisterType.HINT      : hints,
                 RegisterType.FLAGS     : flags}[reg_type]

    @staticmethod
    def find_type(r):
        """Find type of architectural register"""

        if r.startswith("hint_"):
            return RegisterType.HINT

        for ty in RegisterType:
            if r in RegisterType.list_registers(ty):
                return ty

        return None

    @staticmethod
    def is_renamed(ty):
        """Indicate if register type should be subject to renaming"""
        if ty == RegisterType.HINT:
            return False
        return True

    @staticmethod
    def from_string(string):
        """Find registe type from string"""
        string = string.lower()
        return { "fprstack"    : RegisterType.STACK_FPR,
                 "stack"     : RegisterType.STACK_GPR,
                 "fpr"      : RegisterType.FPR,
                 "gpr"       : RegisterType.GPR,
                 "hint"      : RegisterType.HINT,
                 "flags"     : RegisterType.FLAGS}.get(string,None)

    @staticmethod
    def default_reserved():
        """Return the list of registers that should be reserved by default"""
        return set(["flags", "r13", "lr"] + RegisterType.list_registers(RegisterType.HINT))

    @staticmethod
    def default_aliases():
        "Register aliases used by the architecture"
        return { 
                 "lr": "r14",
                #  "sp": "r13" 
                }

# TODO: Comparison can also be done with subs
class Branch:
    """Helper for emitting branches"""

    @staticmethod
    def if_equal(cnt, val, lbl):
        """Emit assembly for a branch-if-equal sequence"""
        yield f"cmp {cnt}, #{val}"
        yield f"beq {lbl}"

    @staticmethod
    def if_greater_equal(cnt, val, lbl):
        """Emit assembly for a branch-if-greater-equal sequence"""
        yield f"cmp {cnt}, #{val}"
        yield f"bge {lbl}"

    @staticmethod
    def unconditional(lbl):
        """Emit unconditional branch"""
        yield f"b {lbl}"


class Loop:
    """Helper functions for parsing and writing simple loops in armv7m

    TODO: Generalize; current implementation too specific about shape of loop"""

    def __init__(self, lbl_start="1", lbl_end="2", loop_init="lr"):
        self.lbl_start = lbl_start
        self.lbl_end   = lbl_end
        self.loop_init = loop_init

    def start(self, loop_cnt, indentation=0, fixup=0, unroll=1, jump_if_empty=None):
        """Emit starting instruction(s) and jump label for loop"""
        indent = ' ' * indentation
        if unroll > 1:
            assert unroll in [1,2,4,8,16,32]
            yield f"{indent}lsr {loop_cnt}, {loop_cnt}, #{int(math.log2(unroll))}"
        if fixup != 0:
            yield f"{indent}sub {loop_cnt}, {loop_cnt}, #{fixup}"
        if jump_if_empty is not None:
            yield f"cbz {loop_cnt}, {jump_if_empty}"
        yield f"{self.lbl_start}:"

    def end(self, other, indentation=0):
        """Emit compare-and-branch at the end of the loop"""
        (reg0, reg1, imm) = other
        indent = ' ' * indentation
        lbl_start = self.lbl_start
        if lbl_start.isdigit():
            lbl_start += "b"

        yield f"{indent}subs {reg0}, {reg1}, {imm}"  # `subs` sets flags
        yield f"{indent}cbnz {reg0}, {lbl_start}"

    @staticmethod
    def extract(source, lbl):
        """Locate a loop with start label `lbl` in `source`.

        We currently only support the following loop forms:

           ```
           loop_lbl:
               {code}
               sub[s] <cnt>, <cnt>, #1
               (cbnz|cbz|bne) <cnt>, loop_lbl
           ```

        """
        assert isinstance(source, list)

        pre  = []
        body = []
        post = []
        loop_lbl_regexp_txt = r"^\s*(?P<label>\w+)\s*:(?P<remainder>.*)$"
        loop_lbl_regexp = re.compile(loop_lbl_regexp_txt)

        # TODO: Allow other forms of looping

        loop_end_regexp_txt = (r"^\s*sub[s]?\s+(?P<reg0>\w+),\s*(?P<reg1>\w+),\s*(?P<imm>#1)",
                               rf"^\s*(cbnz|cbz|bne)\s+(?P<reg0>\w+),\s*{lbl}")
        loop_end_regexp = [re.compile(txt) for txt in loop_end_regexp_txt]
        lines = iter(source)
        l = None
        keep = False
        state = 0 # 0: haven't found loop yet, 1: extracting loop, 2: after loop
        while True:
            if not keep:
                l = next(lines, None)
            keep = False
            if l is None:
                break
            l_str = l.text
            assert isinstance(l, str) is False
            if state == 0:
                p = loop_lbl_regexp.match(l_str)
                if p is not None and p.group("label") == lbl:
                    l = l.copy().set_text(p.group("remainder"))
                    keep = True
                    state = 1
                else:
                    pre.append(l)
                continue
            if state == 1:
                p = loop_end_regexp[0].match(l_str)
                if p is not None:
                    reg0 = p.group("reg0")
                    reg1 = p.group("reg1")
                    imm = p.group("imm")
                    state = 2
                    continue
                body.append(l)
                continue
            if state == 2:
                p = loop_end_regexp[1].match(l_str)
                if p is not None:
                    state = 3
                    continue
                body.append(l)
                continue
            if state == 3:
                post.append(l)
                continue
        if state < 3:
            raise FatalParsingException(f"Couldn't identify loop {lbl}")
        return pre, body, post, lbl, (reg0, reg1, imm)
    
class FatalParsingException(Exception):
    """A fatal error happened during instruction parsing"""

class UnknownInstruction(Exception):
    """The parent instruction class for the given object could not be found"""

class UnknownRegister(Exception):
    """The register could not be found"""

class Instruction:

    class ParsingException(Exception):
        """An attempt to parse an assembly line as a specific instruction failed

        This is a frequently encountered exception since assembly lines are parsed by
        trial and error, iterating over all instruction parsers."""
        def __init__(self, err=None):
            super().__init__(err)

    def __init__(self, *, mnemonic,
                 arg_types_in= None, arg_types_in_out = None, arg_types_out = None):

        if arg_types_in is None:
            arg_types_in = []
        if arg_types_out is None:
            arg_types_out = []
        if arg_types_in_out is None:
            arg_types_in_out = []

        self.mnemonic = mnemonic

        self.args_out_combinations = None
        self.args_in_combinations = None
        self.args_in_out_combinations = None
        self.args_in_out_different = None
        self.args_in_inout_different = None

        self.arg_types_in     = arg_types_in
        self.arg_types_out    = arg_types_out
        self.arg_types_in_out = arg_types_in_out
        self.num_in           = len(arg_types_in)
        self.num_out          = len(arg_types_out)
        self.num_in_out       = len(arg_types_in_out)

        self.args_out_restrictions    = [ None for _ in range(self.num_out)    ]
        self.args_in_restrictions     = [ None for _ in range(self.num_in)     ]
        self.args_in_out_restrictions = [ None for _ in range(self.num_in_out) ]

        self.args_in     = []
        self.args_out    = []
        self.args_in_out = []

        self.addr = None
        self.increment = None
        self.pre_index = None
        self.offset_adjustable = True

        self.immediate = None
        self.datatype = None
        self.index = None
        self.flag = None
        self.width = None
        self.barrel = None

    def extract_read_writes(self):
        """Extracts 'reads'/'writes' clauses from the source line of the instruction"""

        src_line = self.source_line

        def hint_register_name(tag):
            return f"hint_{tag}"

        # Check if the source line is tagged as reading/writing from memory
        def add_memory_write(tag):
            self.num_out += 1
            self.args_out_restrictions.append(None)
            self.args_out.append(hint_register_name(tag))
            self.arg_types_out.append(RegisterType.HINT)

        def add_memory_read(tag):
            self.num_in += 1
            self.args_in_restrictions.append(None)
            self.args_in.append(hint_register_name(tag))
            self.arg_types_in.append(RegisterType.HINT)

        write_tags = src_line.tags.get("writes", [])
        read_tags = src_line.tags.get("reads", [])

        if not isinstance(write_tags, list):
            write_tags = [write_tags]

        if not isinstance(read_tags, list):
            read_tags = [read_tags]

        for w in write_tags:
            add_memory_write(w)

        for r in read_tags:
            add_memory_read(r)

        return self

    def global_parsing_cb(self, a, log=None):
        """Parsing callback triggered after DataFlowGraph parsing which allows modification
        of the instruction in the context of the overall computation.

        This is primarily used to remodel input-outputs as outputs in jointly destructive
        instruction patterns (See Section 4.4, https://eprint.iacr.org/2022/1303.pdf)."""
        _ = log # log is not used
        return False

    def global_fusion_cb(self, a, log=None):
        """Fusion callback triggered after DataFlowGraph parsing which allows fusing
        of the instruction in the context of the overall computation.

        This can be used e.g. to detect eor-eor pairs and replace them by eor3."""
        _ = log # log is not used
        return False

    def write(self):
        """Write the instruction"""
        args = self.args_out + self.args_in_out + self.args_in
        return self.mnemonic + ' ' + ', '.join(args)

    @staticmethod
    def unfold_abbrevs(mnemonic):
        return mnemonic

    def _is_instance_of(self, inst_list):
        for inst in inst_list:
            if isinstance(self,inst):
                return True
        return False

    # TODO Fill in instructions
    def is_load(self):
        """Indicates if an instruction is a load instruction"""
        return self._is_instance_of([ ldr, ldr_with_imm, ldr_with_imm_stack, ldr_with_postinc, ldr_with_inc_writeback ])
    def is_store(self):
        """Indicates if an instruction is a store instruction"""
        return self._is_instance_of([ str_with_imm, str_with_imm_stack, str_with_postinc ])
    def is_load_store_instruction(self):
        """Indicates if an instruction is a load or store instruction"""
        return self.is_load() or self.is_store()

    @classmethod
    def make(cls, src):
        """Abstract factory method parsing a string into an instruction instance."""

    @staticmethod
    def build(c, src, mnemonic, **kwargs):
        """Attempt to parse a string as an instance of an instruction.

        Args:
            c: The target instruction the string should be attempted to be parsed as.
            src: The string to parse.
            mnemonic: The mnemonic of instruction c

        Returns:
            Upon success, the result of parsing src as an instance of c.

        Raises:
            ParsingException: The str argument cannot be parsed as an
                instance of c.
            FatalParsingException: A fatal error during parsing happened
                that's likely a bug in the model.
        """

        if src.split(' ')[0] != mnemonic:
            raise Instruction.ParsingException(f"Mnemonic does not match: {src.split(' ')[0]} vs. {mnemonic}")

        obj = c(mnemonic=mnemonic, **kwargs)

        # Replace <dt> by list of all possible datatypes
        mnemonic = Instruction.unfold_abbrevs(obj.mnemonic)

        expected_args = obj.num_in + obj.num_out + obj.num_in_out
        regexp_txt  = rf"^\s*{mnemonic}"
        if expected_args > 0:
            regexp_txt += r"\s+"
        regexp_txt += ','.join([r"\s*(\w+)\s*" for _ in range(expected_args)])
        regexp = re.compile(regexp_txt)

        p = regexp.match(src)
        if p is None:
            raise Instruction.ParsingException(
                f"Doesn't match basic instruction template {regexp_txt}")

        operands = list(p.groups())

        if obj.num_out > 0:
            obj.args_out = operands[:obj.num_out]
            idx_args_in = obj.num_out
        elif obj.num_in_out > 0:
            obj.args_in_out = operands[:obj.num_in_out]
            idx_args_in = obj.num_in_out
        else:
            idx_args_in = 0

        obj.args_in = operands[idx_args_in:]

        if not len(obj.args_in) == obj.num_in:
            raise FatalParsingException(f"Something wrong parsing {src}: Expect {obj.num_in} input,"
                f" but got {len(obj.args_in)} ({obj.args_in})")

        return obj

    @staticmethod
    def parser(src_line):
        """Global factory method parsing an assembly line into an instance
        of a subclass of Instruction."""
        insts = []
        exceptions = {}
        instnames = []

        src = src_line.text.strip()

        # Iterate through all derived classes and call their parser
        # until one of them hopefully succeeds
        for inst_class in Instruction.all_subclass_leaves:
            try:
                inst = inst_class.make(src)
                instnames = [inst_class.__name__]
                insts = [inst]
                break
            except Instruction.ParsingException as e:
                exceptions[inst_class.__name__] = e

        for i in insts:
            i.source_line = src_line
            i.extract_read_writes()

        if len(insts) == 0:
            logging.error("Failed to parse instruction %s", src)
            logging.error("A list of attempted parsers and their exceptions follows.")
            for i,e in exceptions.items():
                msg = f"* {i + ':':20s} {e}"
                logging.error(msg)
            raise Instruction.ParsingException(
                f"Couldn't parse {src}\nYou may need to add support "\
                  "for a new instruction (variant)?")

        logging.debug("Parsing result for '%s': %s", src, instnames)
        return insts

    def __repr__(self):
        return self.write()
    
class Armv7mInstruction(Instruction):
    """Abstract class representing Armv7m instructions"""

    PARSERS = {}

    @staticmethod
    def _unfold_pattern(src):

        src = re.sub(r"\.",  "\\\\s*\\\\.\\\\s*", src)
        src = re.sub(r"\[", "\\\\s*\\\\[\\\\s*", src)
        src = re.sub(r"\]", "\\\\s*\\\\]\\\\s*", src)

        def pattern_transform(g):
            return \
                f"([{g.group(1).lower()}{g.group(1)}]" +\
                f"(?P<raw_{g.group(1)}{g.group(2)}>[0-9_][0-9_]*)|" +\
                f"([{g.group(1).lower()}{g.group(1)}]<(?P<symbol_{g.group(1)}{g.group(2)}>\\w+)>))"
        src = re.sub(r"<([RS])(\w+)>", pattern_transform, src)  # TODO What does this do?

        # Replace <key> or <key0>, <key1>, ... with pattern
        def replace_placeholders(src, mnemonic_key, regexp, group_name):
            prefix = f"<{mnemonic_key}"
            pattern = f"<{mnemonic_key}>"
            def pattern_i(i):
                return f"<{mnemonic_key}{i}>"

            cnt = src.count(prefix)
            if cnt > 1:
                for i in range(cnt):
                    src = re.sub(pattern_i(i),  f"(?P<{group_name}{i}>{regexp})", src)
            else:
                src = re.sub(pattern, f"(?P<{group_name}>{regexp})", src)

            return src

        flaglist = ["eq","ne","cs","hs","cc","lo","mi","pl","vs","vc","hi","ls","ge","lt","gt","le"]

        flag_pattern = '|'.join(flaglist)
        dt_pattern = "(?:|2|4|8|16)(?:B|H|S|D|b|h|s|d)"  # TODO: Notion of dt can be placed with notion for size in FP instructions
        imm_pattern = "#(\\\\w|\\\\s|/| |-|\\*|\\+|\\(|\\)|=|,)+"
        index_pattern = "[0-9]+"
        width_pattern = "(?:\.w|\.n|)"
        barrel_pattern = "(?:lsl|ror|lsr|asr)"

        src = re.sub(" ", "\\\\s+", src)
        src = re.sub(",", "\\\\s*,\\\\s*", src)

        src = replace_placeholders(src, "imm", imm_pattern, "imm")
        src = replace_placeholders(src, "dt", dt_pattern, "datatype")
        src = replace_placeholders(src, "index", index_pattern, "index")
        src = replace_placeholders(src, "flag", flag_pattern, "flag") # TODO: Are any changes required for IT syntax?
        src = replace_placeholders(src, "width", width_pattern, "width")
        src = replace_placeholders(src, "barrel", barrel_pattern, "barrel")

        src = r"\s*" + src + r"\s*(//.*)?\Z"
        return src

    @staticmethod
    def _build_parser(src):
        regexp_txt = Armv7mInstruction._unfold_pattern(src)
        regexp = re.compile(regexp_txt)

        def _parse(line):
            regexp_result = regexp.match(line)
            if regexp_result is None:
                raise Instruction.ParsingException(f"Does not match instruction pattern {src}"\
                                                   f"[regex: {regexp_txt}]")
            res = regexp.match(line).groupdict()
            items = list(res.items())
            for k, v in items:
                for l in ["symbol_", "raw_"]:
                    if k.startswith(l):
                        del res[k]
                        if v is None:
                            continue
                        k = k[len(l):]
                        res[k] = v
            return res
        return _parse

    @staticmethod
    def get_parser(pattern):
        """Build parser for given AArch64 instruction pattern"""
        if pattern in Armv7mInstruction.PARSERS:
            return Armv7mInstruction.PARSERS[pattern]
        parser = Armv7mInstruction._build_parser(pattern)
        Armv7mInstruction.PARSERS[pattern] = parser
        return parser

    @cache
    @staticmethod
    def _infer_register_type(ptrn):
        if ptrn[0].upper() in ["R"]:
            return RegisterType.GPR
        if ptrn[0].upper() in ["S"]:
            return RegisterType.FPR
        if ptrn[0].upper() in ["T"]:
            return RegisterType.HINT
        raise FatalParsingException(f"Unknown pattern: {ptrn}")

    def __init__(self, pattern, *, inputs=None, outputs=None, in_outs=None, modifiesFlags=False,
                 dependsOnFlags=False):

        self.mnemonic = pattern.split(" ")[0]

        if inputs is None:
            inputs = []
        if outputs is None:
            outputs = []
        if in_outs is None:
            in_outs = []
        arg_types_in     = [Armv7mInstruction._infer_register_type(r) for r in inputs]
        arg_types_out    = [Armv7mInstruction._infer_register_type(r) for r in outputs]
        arg_types_in_out = [Armv7mInstruction._infer_register_type(r) for r in in_outs]

        if modifiesFlags:
            arg_types_out += [RegisterType.FLAGS]
            outputs       += ["flags"]

        if dependsOnFlags:
            arg_types_in += [RegisterType.FLAGS]
            inputs += ["flags"]

        super().__init__(mnemonic=pattern,
                     arg_types_in=arg_types_in,
                     arg_types_out=arg_types_out,
                     arg_types_in_out=arg_types_in_out)

        self.inputs = inputs
        self.outputs = outputs
        self.in_outs = in_outs

        self.pattern = pattern
        self.pattern_inputs = list(zip(inputs, arg_types_in, strict=True))
        self.pattern_outputs = list(zip(outputs, arg_types_out, strict=True))
        self.pattern_in_outs = list(zip(in_outs, arg_types_in_out, strict=True))



    @staticmethod
    def _to_reg(ty, s):
        if ty == RegisterType.GPR:
            c = "r"
        elif ty == RegisterType.FPR:
            c = "s"
        elif ty == RegisterType.HINT:
            c = "t"
        else:
            assert False
        if s.replace('_','').isdigit():
            return f"{c}{s}"
        return s

    @staticmethod
    def _build_pattern_replacement(s, ty, arg):
        if ty == RegisterType.GPR:
            if arg[0] != "r":
                return f"{s[0].upper()}<{arg}>"
            return s[0].lower() + arg[1:]
        if ty == RegisterType.FPR:
            if arg[0] != "s":
                return f"{s[0].upper()}<{arg}>"
            return s[0].lower() + arg[1:]
        if ty == RegisterType.HINT:
            if arg[0] != "t":
                return f"{s[0].upper()}<{arg}>"
            return s[0].lower() + arg[1:]
        raise FatalParsingException(f"Unknown register type ({s}, {ty}, {arg})")

    @staticmethod
    def _instantiate_pattern(s, ty, arg, out):
        if ty == RegisterType.FLAGS:
            return out
        rep = Armv7mInstruction._build_pattern_replacement(s, ty, arg)
        res = out.replace(f"<{s}>", rep)
        if res == out:
            raise FatalParsingException(f"Failed to replace <{s}> by {rep} in {out}!")
        return res

    @staticmethod
    def build_core(obj, res):

        def group_to_attribute(group_name, attr_name, f=None):
            def f_default(x):
                return x
            def group_name_i(i):
                return f"{group_name}{i}"
            if f is None:
                f = f_default
            if group_name in res.keys():
                setattr(obj, attr_name, f(res[group_name]))
            else:
                idxs = [ i for i in range(4) if group_name_i(i) in res.keys() ]
                if len(idxs) == 0:
                    return
                assert idxs == list(range(len(idxs)))
                setattr(obj, attr_name,
                        list(map(lambda i: f(res[group_name_i(i)]), idxs)))

        group_to_attribute('datatype', 'datatype', lambda x: x.lower())
        group_to_attribute('imm', 'immediate', lambda x:x[1:]) # Strip '#'
        group_to_attribute('index', 'index', int)
        group_to_attribute('flag', 'flag')
        group_to_attribute('width', 'width')
        group_to_attribute('barrel', 'barrel')

        for s, ty in obj.pattern_inputs:
            if ty == RegisterType.FLAGS:
                obj.args_in.append("flags")
            else:
                obj.args_in.append(Armv7mInstruction._to_reg(ty, res[s]))
        for s, ty in obj.pattern_outputs:
            if ty == RegisterType.FLAGS:
                obj.args_out.append("flags")
            else:
                obj.args_out.append(Armv7mInstruction._to_reg(ty, res[s]))

        for s, ty in obj.pattern_in_outs:
            obj.args_in_out.append(Armv7mInstruction._to_reg(ty, res[s]))

    @staticmethod
    def build(c, src):
        pattern = getattr(c, "pattern")
        inputs = getattr(c, "inputs", []).copy()
        outputs = getattr(c, "outputs", []).copy()
        in_outs = getattr(c, "in_outs", []).copy()
        modifies_flags = getattr(c,"modifiesFlags", False)
        depends_on_flags = getattr(c,"dependsOnFlags", False)

        if isinstance(src, str):
            # Leave checking the mnemonic out for now; not strictly required
            # Allows xxx.w and xxx.n syntax
            res = Armv7mInstruction.get_parser(pattern)(src)
        else:
            assert isinstance(src, dict)
            res = src

        obj = c(pattern, inputs=inputs, outputs=outputs, in_outs=in_outs,
                modifiesFlags=modifies_flags, dependsOnFlags=depends_on_flags)

        Armv7mInstruction.build_core(obj, res)
        return obj

    @classmethod
    def make(cls, src):
        return Armv7mInstruction.build(cls, src)

    def write(self):
        out = self.pattern
        l = list(zip(self.args_in, self.pattern_inputs))     + \
            list(zip(self.args_out, self.pattern_outputs))   + \
            list(zip(self.args_in_out, self.pattern_in_outs))
        for arg, (s, ty) in l:
            out = Armv7mInstruction._instantiate_pattern(s, ty, arg, out)

        def replace_pattern(txt, attr_name, mnemonic_key, t=None):
            def t_default(x):
                return x
            if t is None:
                t = t_default

            a = getattr(self, attr_name)
            if a is None:
                return txt
            if not isinstance(a, list):
                txt = txt.replace(f"<{mnemonic_key}>", t(a))
                return txt
            for i, v in enumerate(a):
                txt = txt.replace(f"<{mnemonic_key}{i}>", t(v))
            return txt

        out = replace_pattern(out, "immediate", "imm", lambda x: f"#{x}")
        out = replace_pattern(out, "datatype", "dt", lambda x: x.upper())
        out = replace_pattern(out, "flag", "flag")
        out = replace_pattern(out, "index", "index", str)
        out = replace_pattern(out, "width", "width", lambda x: x.lower())
        out = replace_pattern(out, "barrel", "barrel", lambda x: x.lower())

        out = out.replace("\\[", "[")
        out = out.replace("\\]", "]")
        return out

class Armv7mBasicArithmetic(Armv7mInstruction): # pylint: disable=missing-docstring,invalid-name
    pass
class Armv7mShiftedArithmetic(Armv7mInstruction): # pylint: disable=missing-docstring,invalid-name
    pass
class Armv7mLogical(Armv7mInstruction): # pylint: disable=missing-docstring,invalid-name
    pass
class Armv7mShiftedLogical(Armv7mInstruction): # pylint: disable=missing-docstring,invalid-name
    pass
class Armv7mLoadInstruction(Armv7mInstruction): # pylint: disable=missing-docstring,invalid-name
    pass
class Armv7mStoreInstruction(Armv7mInstruction): # pylint: disable=missing-docstring,invalid-name
    pass
class Armv7mFPInstruction(Armv7mInstruction): # pylint: disable=missing-docstring,invalid-name
    pass

# FP
class vmov_gpr(Armv7mFPInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "vmov<width> <Rd>, <Sa>"
    inputs = ["Sa"]
    outputs = ["Rd"]

# Addition

class add(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "add<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]

class add_short(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "add<width> <Rd>, <Ra>"
    inputs = ["Ra"]
    in_outs = ["Rd"]

class add_imm(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "add<width> <Rd>, <Ra>, <imm>"
    inputs = ["Ra"]
    outputs = ["Rd"]

class add_imm_short(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "add<width> <Rd>, <imm>"
    in_outs = ["Rd"]

class add_shifted(Armv7mShiftedArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "add<width> <Rd>, <Ra>, <Rb>, <barrel> <imm>"
    inputs = ["Ra","Rb"]
    outputs = ["Rd"]

class adds(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "adds<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]
    modifiesFlags=True

# Subtraction

class sub(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "sub<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra","Rb"]
    outputs = ["Rd"]

class sub_shifted(Armv7mShiftedArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "sub<width> <Rd>, <Ra>, <Rb>, <barrel> <imm>"
    inputs = ["Ra","Rb"]
    outputs = ["Rd"]

class sub_short(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "sub<width> <Rd>, <Ra>"
    inputs = ["Ra"]
    in_outs = ["Rd"]

class sub_imm_short(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "sub<width> <Ra>, <imm>"
    in_outs = ["Ra"]

# Multiplication
class mul(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "mul<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra","Rb"]
    outputs = ["Rd"]

class smull(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "smull<width> <Ra>, <Rb>, <Rc>, <Rd>"
    inputs = ["Rc","Rd"]
    outputs = ["Ra", "Rb"]

class smlal(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "smlal<width> <Ra>, <Rb>, <Rc>, <Rd>"
    inputs = ["Rc","Rd"]
    in_outs = ["Ra", "Rb"]

# Logical
class log_and(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "and<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]

class log_or(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "orr<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]

class eor(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "eor<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]

class eors(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "eors<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]
    modifiesFlags = True

class eors_short(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "eors<width> <Rd>, <Ra>"
    inputs = ["Ra"]
    in_outs = ["Rd"]
    modifiesFlags = True

class eor_shifted(Armv7mShiftedLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "eor<width> <Rd>, <Ra>, <Rb>, <barrel> <imm>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]

    def write(self):
        self.immediate = simplify(self.immediate)
        return super().write()

class bic(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "bic<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]

class bics(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "bics<width> <Rd>, <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]
    modifiesFlags = True

class bic_shifted(Armv7mShiftedLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "bic<width> <Rd>, <Ra>, <Rb>, <barrel> <imm>"
    inputs = ["Ra", "Rb"]
    outputs = ["Rd"]

class ror(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "ror<width> <Rd>, <Ra>, <imm>"
    inputs = ["Ra"]
    outputs = ["Rd"]

class ror_short(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "ror<width> <Rd>, <imm>"
    in_outs = ["Rd"]

class rors_short(Armv7mLogical): # pylint: disable=missing-docstring,invalid-name
    pattern = "rors<width> <Rd>, <imm>"
    in_outs = ["Rd"]
    modifiesFlags = True

# Load 
class ldr(Armv7mLoadInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "ldr<width> <Rd>, [<Ra>]"
    inputs = ["Ra"]
    outputs = ["Rd"]
    @classmethod
    def make(cls, src):
        obj = Armv7mInstruction.build(cls, src)
        obj.increment = None
        obj.pre_index = None
        obj.addr = obj.args_in[0]
        return obj

class ldr_with_imm(Armv7mLoadInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "ldr<width> <Rd>, [<Ra>, <imm>]"
    inputs = ["Ra"]
    outputs = ["Rd"]
    @classmethod
    def make(cls, src):
        obj = Armv7mInstruction.build(cls, src)
        obj.increment = None
        obj.pre_index = obj.immediate
        obj.addr = obj.args_in[0]
        return obj

class ldr_with_imm_stack(Armv7mLoadInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "ldr<width> <Rd>, [sp, <imm>]"
    inputs = []
    outputs = ["Rd"]
    @classmethod
    def make(cls, src):
        obj = Armv7mInstruction.build(cls, src)
        obj.increment = None
        obj.pre_index = obj.immediate
        obj.addr = "sp"
        return obj

class ldr_with_postinc(Armv7mLoadInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "ldr<width> <Rd>, [<Ra>], <imm>"
    in_outs = ["Ra"]
    outputs = ["Rd"]
    @classmethod
    def make(cls, src):
        obj = Armv7mLoadInstruction.build(cls, src)
        obj.increment = obj.immediate
        obj.pre_index = None
        obj.addr = obj.args_in_out[0]
        return obj

class ldr_with_inc_writeback(Armv7mLoadInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "ldr<width> <Rd>, [<Ra>, <imm>]!"
    in_outs = ["Ra"]
    outputs = ["Rd"]
    @classmethod
    def make(cls, src):
        obj = Armv7mInstruction.build(cls, src)
        obj.increment = obj.immediate
        obj.pre_index = None
        obj.addr = obj.args_in_out[0]
        return obj

# Store
class str_with_imm(Armv7mStoreInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "str<width> <Rd>, [<Ra>, <imm>]"
    inputs = ["Ra", "Rd"]
    outputs = []
    @classmethod
    def make(cls, src):
        obj = Armv7mInstruction.build(cls, src)
        obj.increment = None
        obj.pre_index = obj.immediate
        obj.addr = obj.args_in[0]
        return obj

class str_with_imm_stack(Armv7mStoreInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "str<width> <Rd>, [sp, <imm>]"
    inputs = ["Rd"]
    outputs = []
    @classmethod
    def make(cls, src):
        obj = Armv7mInstruction.build(cls, src)
        obj.increment = None
        obj.pre_index = obj.immediate
        obj.addr = "sp"
        return obj

class str_with_postinc(Armv7mStoreInstruction): # pylint: disable=missing-docstring,invalid-name
    pattern = "str<width> <Rd>, [<Ra>], <imm>"
    inputs = ["Rd"]
    in_outs = ["Ra"]
    @classmethod
    def make(cls, src):
        obj = Armv7mStoreInstruction.build(cls, src)
        obj.increment = obj.immediate
        obj.pre_index = None
        obj.addr = obj.args_in_out[0]
        return obj

# Other
class cmp(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "cmp<width> <Ra>, <Rb>"
    inputs = ["Ra", "Rb"]
    modifiesFlags=True
    dependsOnFlags=True

class cmp_imm(Armv7mBasicArithmetic): # pylint: disable=missing-docstring,invalid-name
    pattern = "cmp<width> <Ra>, <imm>"
    inputs = ["Ra"]
    modifiesFlags=True

# Returns the list of all subclasses of a class which don't have
# subclasses themselves
def all_subclass_leaves(c):

    def has_subclasses(cl):
        return len(cl.__subclasses__()) > 0
    def is_leaf(c):
        return not has_subclasses(c)

    def all_subclass_leaves_core(leaf_lst, todo_lst):
        leaf_lst += filter(is_leaf, todo_lst)
        todo_lst = [ csub
                     for c in filter(has_subclasses, todo_lst)
                     for csub in c.__subclasses__() ]
        if len(todo_lst) == 0:
            return leaf_lst
        return all_subclass_leaves_core(leaf_lst, todo_lst)

    return all_subclass_leaves_core([], [c])

Instruction.all_subclass_leaves = all_subclass_leaves(Instruction)

def iter_armv7m_instructions():
    yield from all_subclass_leaves(Instruction)

def find_class(src):
    for inst_class in iter_armv7m_instructions():
        if isinstance(src,inst_class):
            return inst_class
    raise UnknownInstruction(f"Couldn't find instruction class for {src} (type {type(src)})")

def lookup_multidict(d, inst, default=None):
    instclass = find_class(inst)
    for l,v in d.items():
        # Multidict entries can be the following:
        # - An instruction class. It matches any instruction of that class.
        # - A callable. It matches any instruction returning `True` when passed
        #   to the callable.
        # - A tuple of instruction classes or callables. It matches any instruction
        #   which matches at least one element in the tuple.
        def match(x):
            if inspect.isclass(x):
                return isinstance(inst, x)
            assert callable(x)
            return x(inst)
        if not isinstance(l, tuple):
            l = [l]
        for lp in l:
            if match(lp):
                return v
    if default is None:
        raise UnknownInstruction(f"Couldn't find {instclass} for {inst}")
    return default
