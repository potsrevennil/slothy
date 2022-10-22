# Slothy

## Introduction

This is a derivative of work originally developed and hosted as part of the [PQMX](https://gitlab.com/arm-research/security/pqmx) repository.

### Overview

**Slothy** - **S**uper (**L**azy) **O**ptimization of **T**ricky **H**andwritten assembl**Y** - is an *assembly-level superoptimizer*
for solving the following tasks _simultaneously_:
1. Instruction scheduling,
2. Register allocation, and
3. Software pipelining (= periodic loop interleaving)

It maintains the input code's data flow graph and choice of instructions.

**HeLight55** is the primary instantiation of
Slothy, using models fof the [Armv8.1-M](https://developer.arm.com/documentation/ddi0553/latest) +
[Helium](https://www.arm.com/technologies/helium) architecture and aspects of the
[Cortex-M55r1](https://www.arm.com/products/silicon-ip-cpu/cortex-m/cortex-m55) microarchitecture.

The repository also contains an experimental instantiation **NeLight** for aspects of the AArch64 + Neon architecture.

The goal of Slothy is to enable optimal code for critical workloads which are too complex for other methods
such as autovectorization or intrinsics to provide high performance results, or for which every last % of performance
counts.

Slothy + HeLight55 are the discussed in detail in the paper [Towards perfect CRYSTALS for
Helium](https://eprint.iacr.org/2022/1303).

### How it works

Slothy is essentially a constraint solver frontend: It converts the input source into a computation flow graph and then
lists variables and constraints defining valid instruction schedulings, register renamings, and (in the case of loops)
periodic loop interleavings. Those variables and constraints are then passed to an external constraint solver and, in
case of success, the satisfying assignment returned from the solver converted back into a piece of code. As it stands,
Slothy uses [Google OR-Tools](https://developers.google.com/optimization) as its constraint solver.

HeLight is the result of instantiating Slothy with aspects of the Armv8.1-M + Helium architecture and the Cortex-M55
microarchitecture.

### Performance

In average, Slothy + HeLight + OR-Tools appear to superoptimize Helium assembly of ~50 instructions in a few seconds to
minutes (there's a high variability depending on the difficulty of the optimization, not merely the number of
instructions/constraints), making it practical for real-world kernels.

### IMPORTANT

1. The software optimization information on Cortex-M55 (such as latencies and throughputs of instructions) captured
   in HeLight may contain mistakes. They do _not_ constitute official software optimization guide!
2. HeLight can only optimize code with respect to constraints it knows about, such as latencies and throughput. Those
   being approximative as just mentioned, _and_ not a complete model of the microarchitecture, it is not guaranteed that
   code which HeLight reports as satisfying all constraints is actually stall-free on Cortex-M55. You should always
   double-check the actual performance by running the optimized code on real hardware!

## Getting started

### Dependencies

Slothy and HeLight rely on [Google OR-Tools](https://developers.google.com/optimization) as the underlying constraint
solver, which can be installed via the Python package manager or through compilation from scratch. You need at least
v9.3, and we recommend version >=v9.5.2040 because of
[https://github.com/google/or-tools/issues/3483](https://github.com/google/or-tools/issues/3483), but HeLight has a
workaround in place otherwise.

If you compile from scratch, you need to build the Python interface by setting `BUILD_PYTHON`. For example, if you have
are in the base directory and `build` is the desired build directory, do
```
> cmake -S. -Bbuild -DBUILD_PYTHON:BOOL=ON
> cd build
> make
```
Once done, you can activate OR-Tools virtual Python environment via
```
source {BUILD_DIR}/python/venv/bin/activate
```

You also need `sympy`.

### Quick check

To check that your setup is complete, try the following from the HeLight base directory:

```
> ./helight55-cli examples/naive/simple1.s
```

This should show something like the following:

```
% ./helight55-cli examples/naive/simple1.s
+ ./slothy-cli Arm_v81M Arm_Cortex_M55 examples/naive/simple1.s
INFO:slothy-cli.slothy:Attempt optimization with max 0 stalls...
INFO:slothy-cli.slothy.input:Statically assign global input r0 to register r0
INFO:slothy-cli.slothy.input:Statically assign global input q1 to register q1
INFO:slothy-cli.slothy.input:Statically assign global input r1 to register r1
INFO:slothy-cli.slothy:No objective -- any satisfying solution is fine
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_0_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Attempt optimization with max 1 stalls...
INFO:slothy-cli.slothy.input:Statically assign global input r0 to register r0
INFO:slothy-cli.slothy.input:Statically assign global input q1 to register q1
INFO:slothy-cli.slothy.input:Statically assign global input r1 to register r1
INFO:slothy-cli.slothy:No objective -- any satisfying solution is fine
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_1_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Found 1 solutions so far... objective value = 0.0 (no objective)
INFO:slothy-cli.slothy:Input const renamed to r12
INFO:slothy-cli.slothy:OPTIMAL, wall time: 0.004099
INFO:slothy-cli.slothy.selfcheck:OK!
        vldrw.u32 q0, [r0]           // *...
        vmla.s32 q0, q1, r12         // .*..
        // gap                       // ....
        vmla.s32 q0, q1, r12         // ..*.
        vstrw.u32 q0, [r1]           // ...*

        // original source code
        // vldrw.u32 q0, [r0]          // *...
        // vmla.s32 q0, q1, const      // .*..
        // vmla.s32 q0, q1, const      // ..*.
        // vstrw.u32 q0, [r1]          // ...*
```

### Basic usage

There are two basic forms of usage for `Slothy`:  Stateless and stateful.

_Stateless / one-shot optimization_ takes a triple of (a) Slothy configuration, (a) input assembly, (c) list of output
registers, and conducts a single optimization attempt (in the sense that one constraint model is created and passed to
the underlying constraint solver). On success, the one-shot optimization returns a result object, including not only
optimized source code but also other information like the permutation and renamings that relate it to the original
source code.

_Stateful optimization_ is a shim convenience wrapper around multiple invocations of the one-shot
  optimization. You can load entire assembly files, including register aliases and macro definitions, and perform
  multiple passes of cut-optimize-replace for selected regions in the code. Moreover, stateful optimization implements
  some heuristics for the optimization of large assembly snippets for which a one-shot optimization appears
  infeasible. It also implements a binary search for the minimization of stalls (there is also the option to make the
  number of stalls a flexible varaible in the constraint model, but this does not appear to perform well so far).

#### Stateless / one-shot optimization

TODO: Document

#### Stateful optimization

For stateful optimization, the basic usage flow is as follows:

1. Setup a `Slothy` instance, passing the architecture and target microarchitecture modules as arguments.
   For example, for Helight, do `helight = Slothy(targets.arm_v81m.arch_v81m, targets.arm_v81m.cortex_m55r1)`.
2. Load the source code to optimize via `load_source_from_file()`
3. Modify the default configuration as desired
4. Call `helight.optimize(first=START_LABEL, end=END_LABEL)` to optimize and replace the part of the current source code
   between the given labels. Alternatively, call `helight.optimize_loop(loop_lbl=LABEL)` to do the same for a loop
   starting at label `LABEL` (the end will be detected automatically).
5. If you have multiple sections to be optimized, repeat 3 and 4 above.
6. Print and/or save the final source code via `helight.print_code()` or `helight.write_source_to_file()`.

If you want to optimize the intermediate code between two loops which have been optimized via software pipelining,
you'll need to know the dependencies carried across the optimized iterations. After a call to `helight.optimize_loop()`,
you can query those as `helight.result.kernel.kernel_input_output`. More generally,
`helight.result.{preamble,kernel,postamble}` contains result objects for the optimization of loop preamble, kernel, and
postamble, if applicable.

You may find Slothy complaining about ambiguity of register types if you use symbolic registers rather names sthan
architectural ones. In this case, you need to set `config.typing_hints`. For example, if the symbolic register name
`foo` should be a general purpose register, you add `config.typing_hints['foo'] = RegisterType.GPR`.

See [example.py](example.py) for many examples of the usage of Slothy/Helight from Python.

Alternatively, you can use `helight55-cli`, which however is less flexible.

## Further examples

The [examples](examples/naive) directory contains numerous exemplary assembly snippets. To try them, either use
`helight55-cli` or `python3 example.py --examples={YOUR_EXAMPLE}`. See `python3 examples.py --help` for the list of
all available examples.

For the rest of the section, we go through some of the examples to give the reader a feel for the power and usage of HeLight.

### Optimization of a simple assembly snippet

```
% ./helight55-cli examples/naive/simple0.s
+ ./slothy-cli Arm_v81M Arm_Cortex_M55 examples/naive/simple0.s
INFO:slothy-cli.slothy:Attempt optimization with max 0 stalls...
INFO:slothy-cli.slothy:No objective -- any satisfying solution is fine
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_0_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Attempt optimization with max 1 stalls...
INFO:slothy-cli.slothy:No objective -- any satisfying solution is fine
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_1_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Found 1 solutions so far... objective value = 0.0 (no objective)
INFO:slothy-cli.slothy:Input inA renamed to r5
INFO:slothy-cli.slothy:Input inB renamed to r0
INFO:slothy-cli.slothy:OPTIMAL, wall time: 0.028703000000000003
INFO:slothy-cli.slothy.selfcheck:OK!
        vldrw.u32 q0, [r5, #16]           // .*..............
        // gap                            // ................
        vldrw.u32 q4, [r0] , #16          // ...*............
        vmulh.u32 q6, q0, q4              // .....*..........
        vldrw.u32 q0, [r5]                // *...............
        vadd.u32 q5, q6, q6               // .........*......
        vmulh.u32 q1, q0, q4              // ....*...........
        vadd.u32 q7, q5, q4               // ..........*.....
        vldrw.u32 q0, [r5, #32]           // ..*.............
        vadd.u32 q6, q1, q1               // .......*........
        vmulh.u32 q0, q0, q4              // ......*.........
        vadd.u32 q1, q6, q4               // ........*.......
        vstrw.u32 q1, [r5] , #48          // ...............*
        vadd.u32 q6, q0, q0               // ...........*....
        vstrw.u32 q7, [r5, #-32]          // .............*..
        vadd.u32 q2, q6, q4               // ............*...
        vstrw.u32 q2, [r5, #-16]          // ..............*.

        // original source code
        // vldrw.u32 q0, [inA]            // ...*............
        // vldrw.u32 q1, [inA, #16]       // *...............
        // vldrw.u32 q2, [inA, #32]       // .......*........
        // vldrw.u32 q7, [inB] , #16      // .*..............
        // vmulh.u32 q0, q0, q7           // .....*..........
        // vmulh.u32 q1, q1, q7           // ..*.............
        // vmulh.u32 q2, q2, q7           // .........*......
        // vadd.u32 q0, q0, q0            // ........*.......
        // vadd.u32 q0, q0, q7            // ..........*.....
        // vadd.u32 q1, q1, q1            // ....*...........
        // vadd.u32 q1, q1, q7            // ......*.........
        // vadd.u32 q2, q2, q2            // ............*...
        // vadd.u32 q2, q2, q7            // ..............*.
        // vstrw.u32 q1, [inA, #16]       // .............*..
        // vstrw.u32 q2, [inA, #32]       // ...............*
        // vstrw.u32 q0, [inA] , #48      // ...........*....
```

To write the output to a file, use

```
> ./helight55-cli examples/naive/simple0.s --output examples/opt/simple0.s
```

### Optimization of a simple snippet, software pipelining ("loop mode")

```
% ./helight55-cli examples/naive/simple0.s -c sw_pipelining.enabled=True
+ ./slothy-cli Arm_v81M Arm_Cortex_M55 examples/naive/simple0.s -c sw_pipelining.enabled=True
INFO:slothy-cli:- Setting configuration option sw_pipelining.enabled to value True
INFO:slothy-cli.slothy:Attempt optimization with max 0 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_0_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Found 1 solutions so far... objective value = 11.0 (minimize iteration overlapping)
INFO:slothy-cli.slothy:Found 2 solutions so far... objective value = 6.0 (minimize iteration overlapping)
INFO:slothy-cli.slothy:Found 3 solutions so far... objective value = 5.0 (minimize iteration overlapping)
INFO:slothy-cli.slothy:Number of early instructions: 5
INFO:slothy-cli.slothy:Input inA renamed to r5
INFO:slothy-cli.slothy:Input inB renamed to r4
INFO:slothy-cli.slothy:OPTIMAL, wall time: 0.407965
INFO:slothy-cli.slothy.selfcheck:OK!
        vmulh.u32 q1, q0, q6             // ....*...........
        vadd.u32 q2, q4, q6              // ............*...
        vldrw.u32 q7, [r5, #16]          // .*..............
        vadd.u32 q5, q1, q1              // .......*........
        vstrw.u32 q2, [r5, #32]          // ..............*.
        vmulh.u32 q7, q7, q6             // .....*..........
        vadd.u32 q5, q5, q6              // ........*.......
        vldrw.u32 q0, [r5, #48]          // e...............
        vadd.u32 q2, q7, q7              // .........*......
        vldrw.u32 q1, [r5, #80]          // ..e.............
        vadd.u32 q3, q2, q6              // ..........*.....
        vldrw.u32 q6, [r4] , #16         // ...e............
        vmulh.u32 q4, q1, q6             // ......e.........
        vstrw.u32 q3, [r5, #16]          // .............*..
        vadd.u32 q4, q4, q4              // ...........e....
        vstrw.u32 q5, [r5] , #48         // ...............*

        // original source code
        // vldrw.u32 q0, [inA]            // e........................
        // vldrw.u32 q1, [inA, #16]       // ...........*.............
        // vldrw.u32 q2, [inA, #32]       // ..e......................
        // vldrw.u32 q7, [inB] , #16      // ....e....................
        // vmulh.u32 q0, q0, q7           // .........*...............
        // vmulh.u32 q1, q1, q7           // ..............*..........
        // vmulh.u32 q2, q2, q7           // .....e...................
        // vadd.u32 q0, q0, q0            // ............*............
        // vadd.u32 q0, q0, q7            // ...............*.........
        // vadd.u32 q1, q1, q1            // .................*.......
        // vadd.u32 q1, q1, q7            // ...................*.....
        // vadd.u32 q2, q2, q2            // .......e.................
        // vadd.u32 q2, q2, q7            // ..........*..............
        // vstrw.u32 q1, [inA, #16]       // ......................*..
        // vstrw.u32 q2, [inA, #32]       // .............*...........
        // vstrw.u32 q0, [inA] , #48      // ........................*
```

Here, `e` indicates that the instruction is an early instruction for the next iteration.

### Very complex loop

```
./helight55-cli examples/naive/crt.s -c typing_hints="{mod_p_tw:GPR,const_prshift:GPR,p_inv_mod_q_tw:GPR,p_inv_mod_q:GPR,const_shift9:GPR}"
```

The typing hints are necessary here for HeLight to disambiguate between
scalar/vector and vector/vector variants of some instructions. The above then tries to optimize a loop implementing the
interpolation step in the Chinese Remainder Theorem (CRT). The loop is very hard to optimize due to a large number of
multiplications and a large number of add/sub/logical operations in the end, and one cannot do better than 3 stalls as witnessed by the output:

```
% ./helight55-cli examples/naive/crt.s -c sw_pipelining.enabled=True -c typing_hints="{mod_p_tw:GPR,const_prshift:GPR,p_inv_mod_q_tw:GPR,p_inv_mod_q:GPR,const_shift9:GPR}"
+ ./slothy-cli Arm_v81M Arm_Cortex_M55 examples/naive/crt.s -c sw_pipelining.enabled=True -c 'typing_hints={mod_p_tw:GPR,const_prshift:GPR,p_inv_mod_q_tw:GPR,p_inv_mod_q:GPR,const_shift9:GPR}'
INFO:slothy-cli:- Setting configuration option sw_pipelining.enabled to value True
INFO:slothy-cli:- Setting configuration option typing_hints to value {'mod_p_tw': GPR, 'const_prshift': GPR, 'p_inv_mod_q_tw': GPR, 'p_inv_mod_q': GPR, 'const_shift9': GPR}
INFO:slothy-cli.slothy:Attempt optimization with max 0 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_0_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Attempt optimization with max 1 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_1_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Attempt optimization with max 2 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_2_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Attempt optimization with max 4 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_4_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Attempt optimization with max 8 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_8_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Found 1 solutions so far... objective value = 3.0 (minimize iteration overlapping)
INFO:slothy-cli.slothy:Number of early instructions: 3
INFO:slothy-cli.slothy:Input src0 renamed to r9
INFO:slothy-cli.slothy:Input mod_p_tw renamed to r0
INFO:slothy-cli.slothy:Input const_prshift renamed to r11
INFO:slothy-cli.slothy:Input mod_p renamed to r1
INFO:slothy-cli.slothy:Input src1 renamed to r10
INFO:slothy-cli.slothy:Input p_inv_mod_q_tw renamed to r2
INFO:slothy-cli.slothy:Input p_inv_mod_q renamed to r5
INFO:slothy-cli.slothy:Input mod_q_neg renamed to r6
INFO:slothy-cli.slothy:Input const_shift9 renamed to r12
INFO:slothy-cli.slothy:Input qmask renamed to q6
INFO:slothy-cli.slothy:Input rcarry renamed to r7
INFO:slothy-cli.slothy:Input rcarry_red renamed to r8
INFO:slothy-cli.slothy:Input const_rshift22 renamed to r4
INFO:slothy-cli.slothy:Input dst renamed to r3
INFO:slothy-cli.slothy:OPTIMAL, wall time: 1.3712950000000002
INFO:slothy-cli.slothy.selfcheck:OK!
INFO:slothy-cli.slothy:Attempt optimization with max 6 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_6_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Found 1 solutions so far... objective value = 5.0 (minimize iteration overlapping)
INFO:slothy-cli.slothy:Number of early instructions: 5
INFO:slothy-cli.slothy:Input src0 renamed to r9
INFO:slothy-cli.slothy:Input mod_p_tw renamed to r0
INFO:slothy-cli.slothy:Input const_prshift renamed to r11
INFO:slothy-cli.slothy:Input mod_p renamed to r1
INFO:slothy-cli.slothy:Input src1 renamed to r10
INFO:slothy-cli.slothy:Input p_inv_mod_q_tw renamed to r2
INFO:slothy-cli.slothy:Input p_inv_mod_q renamed to r5
INFO:slothy-cli.slothy:Input mod_q_neg renamed to r6
INFO:slothy-cli.slothy:Input const_shift9 renamed to r12
INFO:slothy-cli.slothy:Input qmask renamed to q6
INFO:slothy-cli.slothy:Input rcarry renamed to r7
INFO:slothy-cli.slothy:Input rcarry_red renamed to r8
INFO:slothy-cli.slothy:Input const_rshift22 renamed to r4
INFO:slothy-cli.slothy:Input dst renamed to r3
INFO:slothy-cli.slothy:OPTIMAL, wall time: 1.142423
INFO:slothy-cli.slothy.selfcheck:OK!
INFO:slothy-cli.slothy:Attempt optimization with max 5 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_5_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Found 1 solutions so far... objective value = 7.0 (minimize iteration overlapping)
INFO:slothy-cli.slothy:Number of early instructions: 7
INFO:slothy-cli.slothy:Input src0 renamed to r9
INFO:slothy-cli.slothy:Input mod_p_tw renamed to r0
INFO:slothy-cli.slothy:Input const_prshift renamed to r11
INFO:slothy-cli.slothy:Input mod_p renamed to r1
INFO:slothy-cli.slothy:Input src1 renamed to r10
INFO:slothy-cli.slothy:Input p_inv_mod_q_tw renamed to r2
INFO:slothy-cli.slothy:Input p_inv_mod_q renamed to r5
INFO:slothy-cli.slothy:Input mod_q_neg renamed to r6
INFO:slothy-cli.slothy:Input const_shift9 renamed to r12
INFO:slothy-cli.slothy:Input qmask renamed to q6
INFO:slothy-cli.slothy:Input rcarry renamed to r7
INFO:slothy-cli.slothy:Input rcarry_red renamed to r8
INFO:slothy-cli.slothy:Input const_rshift22 renamed to r4
INFO:slothy-cli.slothy:Input dst renamed to r3
INFO:slothy-cli.slothy:OPTIMAL, wall time: 1.008335
INFO:slothy-cli.slothy.selfcheck:OK!
        vrshr.s32 q5, q2, #(SHIFT)         // ........*..............
        vmul.u32 q2, q3, r5                // .......*...............
        // gap                             // .......................
        vmla.s32 q2, q5, r6                // .........*.............
        // gap                             // .......................
        vmul.u32 q3, q2, r1                // ..........*............
        // gap                             // .......................
        vqdmulh.s32 q7, q2, r1             // ...........*...........
        vshr.u32 q2, q3, #22               // ............*..........
        vmul.u32 q4, q7, r12               // .............*.........
        // gap                             // .......................
        vorr.u32 q4, q2, q4                // ...............*.......
        vldrw.u32 q7, [r10]                // ....e..................
        vshlc q4, r7, #32                  // ................*......
        // gap                             // .......................
        vadd.u32 q5, q0, q4                // .................*.....
        vldrw.u32 q0, [r9]                 // e......................
        vand.u32 q1, q3, q6                // ..............*........
        vqdmulh.s32 q4, q0, r0             // .e.....................
        vadd.u32 q2, q1, q5                // ..................*....
        vqrdmulh.s32 q4, q4, r11           // ..e....................
        vand.u32 q1, q2, q6                // ...................*...
        vmla.s32 q0, q4, r1                // ...e...................
        vshlc q2, r8, #32                  // ....................*..
        vqdmlah.s32 q1, q2, r4             // .....................*.
        vsub.u32 q3, q7, q0                // .....e.................
        vqdmulh.s32 q2, q3, r2             // ......e................
        vstrw.u32 q1, [r3]                 // ......................*

        // original source code
        // vldrw.u32 in0, [src0]                          // ...e..................................
        // vqdmulh.s32 diff, in0, mod_p_tw                // .....e................................
        // vqrdmulh.s32 tmp, diff, const_prshift          // .......e..............................
        // vmla.s32 in0, tmp, mod_p                       // .........e............................
        // vldrw.u32 in1, [src1]                          // e.....................................
        // vsub.u32 diff, in1, in0                        // ............e.........................
        // vqdmulh.s32 tmp, diff, p_inv_mod_q_tw          // .............e........................
        // vmul.u32 diff, diff, p_inv_mod_q               // ................*.....................
        // vrshr.s32 tmp, tmp, #(SHIFT)                   // ...............*......................
        // vmla.s32 diff, tmp, mod_q_neg                  // .................*....................
        // vmul.u32 quot_low, diff, mod_p                 // ..................*...................
        // vqdmulh.s32 tmp, diff, mod_p                   // ...................*..................
        // vshr.u32 tmpp, quot_low, #22                   // ....................*.................
        // vmul.u32 tmp, tmp, const_shift9                // .....................*................
        // vand.u32 quot_low, quot_low, qmask             // ...........................*..........
        // vorr.u32 tmpp, tmpp, tmp                       // ......................*...............
        // vshlc tmpp, rcarry, #32                        // ........................*.............
        // vadd.u32 in0, in0, tmpp                        // .........................*............
        // vadd.u32 tmpp, quot_low, in0                   // .............................*........
        // vand.u32 red_tmp, tmpp, qmask                  // ...............................*......
        // vshlc tmpp, rcarry_red, #32                    // .................................*....
        // vqdmlah.s32 red_tmp, tmpp, const_rshift22      // ..................................*...
        // vstrw.u32 red_tmp, [dst]                       // .....................................*
```

However, allowing HeLight to double the loop body via `-c sw_pipelining.unroll=2` makes it possible to find a perfect solution
which overlaps the add/sub/logical-heavy part of one iteration with the mul-heavy part of the next:

```
% ./helight55-cli examples/naive/crt.s -c sw_pipelining.enabled=True -c typing_hints="{mod_p_tw:GPR,const_prshift:GPR,p_inv_mod_q_tw:GPR,p_inv_mod_q:GPR,const_shift9:GPR}" -c sw_pipelining.unroll=2
+ ./slothy-cli Arm_v81M Arm_Cortex_M55 examples/naive/crt.s -c sw_pipelining.enabled=True -c 'typing_hints={mod_p_tw:GPR,const_prshift:GPR,p_inv_mod_q_tw:GPR,p_inv_mod_q:GPR,const_shift9:GPR}' -c sw_pipelining.unroll=2
INFO:slothy-cli:- Setting configuration option sw_pipelining.enabled to value True
INFO:slothy-cli:- Setting configuration option typing_hints to value {'mod_p_tw': GPR, 'const_prshift': GPR, 'p_inv_mod_q_tw': GPR, 'p_inv_mod_q': GPR, 'const_shift9': GPR}
INFO:slothy-cli:- Setting configuration option sw_pipelining.unroll to value 2
INFO:slothy-cli.slothy:Attempt optimization with max 0 stalls...
INFO:slothy-cli.slothy:Set objective: minimize iteration overlapping
INFO:slothy-cli.slothy:Writing model to slothy-cli_slothy_0_stalls.txt...
INFO:slothy-cli.slothy:Invoking external constraint solver...
INFO:slothy-cli.slothy:Found 1 solutions so far... objective value = 11.0 (minimize iteration overlapping)
INFO:slothy-cli.slothy:Number of early instructions: 11
INFO:slothy-cli.slothy:Input src0 renamed to r11
INFO:slothy-cli.slothy:Input mod_p_tw renamed to r5
INFO:slothy-cli.slothy:Input const_prshift renamed to r6
INFO:slothy-cli.slothy:Input mod_p renamed to r7
INFO:slothy-cli.slothy:Input src1 renamed to r8
INFO:slothy-cli.slothy:Input p_inv_mod_q_tw renamed to r0
INFO:slothy-cli.slothy:Input p_inv_mod_q renamed to r3
INFO:slothy-cli.slothy:Input mod_q_neg renamed to r1
INFO:slothy-cli.slothy:Input const_shift9 renamed to r2
INFO:slothy-cli.slothy:Input qmask renamed to q4
INFO:slothy-cli.slothy:Input rcarry renamed to r4
INFO:slothy-cli.slothy:Input rcarry_red renamed to r9
INFO:slothy-cli.slothy:Input const_rshift22 renamed to r10
INFO:slothy-cli.slothy:Input dst renamed to r12
INFO:slothy-cli.slothy:OPTIMAL, wall time: 12.57043
INFO:slothy-cli.slothy.selfcheck:OK!
        vqdmulh.s32 q1, q7, r7             // ...........*..................................
        vshr.u32 q7, q2, #22               // ............*.................................
        vmul.u32 q0, q1, r2                // .............*................................
        vldrw.u32 q5, [r11]                // .......................*......................
        vqdmulh.s32 q3, q5, r5             // ........................*.....................
        vorr.u32 q7, q7, q0                // ...............*..............................
        vqrdmulh.s32 q0, q3, r6            // .........................*....................
        vshlc q7, r4, #32                  // ................*.............................
        vmla.s32 q5, q0, r7                // ..........................*...................
        vldrw.u32 q0, [r8]                 // ...........................*..................
        vsub.u32 q0, q0, q5                // ............................*.................
        vqdmulh.s32 q3, q0, r0             // .............................*................
        vadd.u32 q7, q6, q7                // .................*............................
        vmul.u32 q1, q0, r3                // ..............................*...............
        vrshr.s32 q0, q3, #(SHIFT)         // ...............................*..............
        vldrw.u32 q6, [r11]                // e.............................................
        vmla.s32 q1, q0, r1                // ................................*.............
        vand.u32 q3, q2, q4                // ..............*...............................
        vmul.u32 q0, q1, r7                // .................................*............
        vadd.u32 q7, q3, q7                // ..................*...........................
        vqdmulh.s32 q3, q1, r7             // ..................................*...........
        vand.u32 q2, q0, q4                // .....................................*........
        vmul.u32 q1, q3, r2                // ....................................*.........
        vshr.u32 q0, q0, #22               // ...................................*..........
        vqdmulh.s32 q3, q6, r5             // .e............................................
        vorr.u32 q0, q0, q1                // ......................................*.......
        vqrdmulh.s32 q1, q3, r6            // ..e...........................................
        vand.u32 q3, q7, q4                // ...................*..........................
        vmla.s32 q6, q1, r7                // ...e..........................................
        vshlc q7, r9, #32                  // ....................*.........................
        vqdmlah.s32 q3, q7, r10            // .....................*........................
        vshlc q0, r4, #32                  // .......................................*......
        vldrw.u32 q1, [r8]                 // ....e.........................................
        vsub.u32 q7, q1, q6                // .....e........................................
        vqdmulh.s32 q1, q7, r0             // ......e.......................................
        vadd.u32 q5, q5, q0                // ........................................*.....
        vstrw.u32 q3, [r12]                // ......................*.......................
        vrshr.s32 q1, q1, #(SHIFT)         // ........e.....................................
        vmul.u32 q7, q7, r3                // .......e......................................
        vadd.u32 q0, q2, q5                // .........................................*....
        vmla.s32 q7, q1, r1                // .........e....................................
        vand.u32 q1, q0, q4                // ..........................................*...
        vmul.u32 q2, q7, r7                // ..........e...................................
        vshlc q0, r9, #32                  // ...........................................*..
        vqdmlah.s32 q1, q0, r10            // ............................................*.
        vstrw.u32 q1, [r12]                // .............................................*

        // original source code
        // vldrw.u32 in0, [src0]                          // e............................................................................
        // vqdmulh.s32 diff, in0, mod_p_tw                // .........e...................................................................
        // vqrdmulh.s32 tmp, diff, const_prshift          // ...........e.................................................................
        // vmla.s32 in0, tmp, mod_p                       // .............e...............................................................
        // vldrw.u32 in1, [src1]                          // .................e...........................................................
        // vsub.u32 diff, in1, in0                        // ..................e..........................................................
        // vqdmulh.s32 tmp, diff, p_inv_mod_q_tw          // ...................e.........................................................
        // vmul.u32 diff, diff, p_inv_mod_q               // .......................e.....................................................
        // vrshr.s32 tmp, tmp, #(SHIFT)                   // ......................e......................................................
        // vmla.s32 diff, tmp, mod_q_neg                  // .........................e...................................................
        // vmul.u32 quot_low, diff, mod_p                 // ...........................e.................................................
        // vqdmulh.s32 tmp, diff, mod_p                   // ...............................*.............................................
        // vshr.u32 tmpp, quot_low, #22                   // ................................*............................................
        // vmul.u32 tmp, tmp, const_shift9                // .................................*...........................................
        // vand.u32 quot_low, quot_low, qmask             // ................................................*............................
        // vorr.u32 tmpp, tmpp, tmp                       // ....................................*........................................
        // vshlc tmpp, rcarry, #32                        // ......................................*......................................
        // vadd.u32 in0, in0, tmpp                        // ...........................................*.................................
        // vadd.u32 tmpp, quot_low, in0                   // ..................................................*..........................
        // vand.u32 red_tmp, tmpp, qmask                  // ..........................................................*..................
        // vshlc tmpp, rcarry_red, #32                    // ............................................................*................
        // vqdmlah.s32 red_tmp, tmpp, const_rshift22      // .............................................................*...............
        // vstrw.u32 red_tmp, [dst]                       // ...................................................................*.........
        // vldrw.u32 in0, [src0]                          // ..................................*..........................................
        // vqdmulh.s32 diff, in0, mod_p_tw                // ...................................*.........................................
        // vqrdmulh.s32 tmp, diff, const_prshift          // .....................................*.......................................
        // vmla.s32 in0, tmp, mod_p                       // .......................................*.....................................
        // vldrw.u32 in1, [src1]                          // ........................................*....................................
        // vsub.u32 diff, in1, in0                        // .........................................*...................................
        // vqdmulh.s32 tmp, diff, p_inv_mod_q_tw          // ..........................................*..................................
        // vmul.u32 diff, diff, p_inv_mod_q               // ............................................*................................
        // vrshr.s32 tmp, tmp, #(SHIFT)                   // .............................................*...............................
        // vmla.s32 diff, tmp, mod_q_neg                  // ...............................................*.............................
        // vmul.u32 quot_low, diff, mod_p                 // .................................................*...........................
        // vqdmulh.s32 tmp, diff, mod_p                   // ...................................................*.........................
        // vshr.u32 tmpp, quot_low, #22                   // ......................................................*......................
        // vmul.u32 tmp, tmp, const_shift9                // .....................................................*.......................
        // vand.u32 quot_low, quot_low, qmask             // ....................................................*........................
        // vorr.u32 tmpp, tmpp, tmp                       // ........................................................*....................
        // vshlc tmpp, rcarry, #32                        // ..............................................................*..............
        // vadd.u32 in0, in0, tmpp                        // ..................................................................*..........
        // vadd.u32 tmpp, quot_low, in0                   // ......................................................................*......
        // vand.u32 red_tmp, tmpp, qmask                  // ........................................................................*....
        // vshlc tmpp, rcarry_red, #32                    // ..........................................................................*..
        // vqdmlah.s32 red_tmp, tmpp, const_rshift22      // ...........................................................................*.
        // vstrw.u32 red_tmp, [dst]                       // ............................................................................*
```

* Further examples

Many further examples can be found in [examples.py](examples.py) which illustrate how to instruct HeLight from
within Python. The input sources to those examples can be found in [examples/naive](examples/naive), and the optimized
versions are in [examples/opt](examples/opt).