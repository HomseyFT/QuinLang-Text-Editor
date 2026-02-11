from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Tuple, Callable, Optional
from compiler.bytecode import OpCode, Instruction, Bytecode


@dataclass
class FunctionInfo:
    name: str
    entry_pc: int
    num_locals: int
    num_params: int


class ExecutionStopped(Exception):
    """Raised when execution is stopped externally."""
    pass


class QuinVM:
    def __init__(
        self,
        code: Bytecode,
        functions: List[FunctionInfo],
        strings: Dict[int, str],
        output_callback: Optional[Callable[[str], None]] = None,
    ):
        self.code = code
        self.functions = functions
        # map name -> index for convenience
        self.func_index: Dict[str, int] = {f.name: i for i, f in enumerate(functions)}
        self.strings = strings
        self._output_callback = output_callback
        self._stop_requested = False

        self.stack: List[int] = []              # value stack
        self.call_stack: List[Tuple[int, List[int]]] = []  # (return_pc, locals)
        self.pc: int = 0
        self.locals: List[int] = []             # current frame locals

    def request_stop(self):
        """Request the VM to stop execution."""
        self._stop_requested = True

    def _output(self, text: str):
        """Output text via callback or print."""
        if self._output_callback:
            self._output_callback(text)
        else:
            print(text, end="")

    def run_main(self) -> int:
        if "main" not in self.func_index:
            raise RuntimeError("No 'main' function defined")
        fn_id = self.func_index["main"]
        fn = self.functions[fn_id]
        # set up initial frame
        self.locals = [0] * fn.num_locals
        self.pc = fn.entry_pc
        return self._run()

    def _run(self) -> int:
        code = self.code
        while self.pc < len(code):
            # Check for stop request
            if self._stop_requested:
                raise ExecutionStopped("Execution stopped by user")

            instr = code[self.pc]
            op = instr.op
            arg = instr.arg
            self.pc += 1

            if op is OpCode.PUSH_INT:
                self.stack.append(int(arg))

            elif op is OpCode.LOAD_LOCAL:
                self.stack.append(self.locals[arg])

            elif op is OpCode.STORE_LOCAL:
                val = self.stack.pop()
                self.locals[arg] = val

            elif op is OpCode.ADD:
                b = self.stack.pop(); a = self.stack.pop()
                self.stack.append((a + b) & 0xFFFF)

            elif op is OpCode.SUB:
                b = self.stack.pop(); a = self.stack.pop()
                self.stack.append((a - b) & 0xFFFF)

            elif op is OpCode.MUL:
                b = self.stack.pop(); a = self.stack.pop()
                self.stack.append((a * b) & 0xFFFF)

            elif op is OpCode.DIV:
                b = self.stack.pop(); a = self.stack.pop()
                if b == 0:
                    raise RuntimeError("Division by zero")
                # signed division
                self.stack.append(int(a) // int(b))

            elif op is OpCode.NEG:
                a = self.stack.pop()
                self.stack.append((-int(a)) & 0xFFFF)

            elif op in (OpCode.CMP_EQ, OpCode.CMP_NE, OpCode.CMP_LT, OpCode.CMP_LE, OpCode.CMP_GT, OpCode.CMP_GE):
                b = self.stack.pop(); a = self.stack.pop()
                if op is OpCode.CMP_EQ:
                    res = int(a == b)
                elif op is OpCode.CMP_NE:
                    res = int(a != b)
                elif op is OpCode.CMP_LT:
                    res = int(a < b)
                elif op is OpCode.CMP_LE:
                    res = int(a <= b)
                elif op is OpCode.CMP_GT:
                    res = int(a > b)
                else:  # CMP_GE
                    res = int(a >= b)
                self.stack.append(res)

            elif op is OpCode.NOT:
                a = self.stack.pop()
                self.stack.append(0 if a else 1)

            elif op is OpCode.JMP:
                self.pc = int(arg)

            elif op is OpCode.JZ:
                v = self.stack.pop()
                if v == 0:
                    self.pc = int(arg)

            elif op is OpCode.JNZ:
                v = self.stack.pop()
                if v != 0:
                    self.pc = int(arg)

            elif op is OpCode.CALL:
                fn_id = int(arg)
                fn = self.functions[fn_id]
                # pop arguments from stack (rightmost pushed last), place into new frame locals[0..num_params-1]
                args: List[int] = []
                for _ in range(fn.num_params):
                    if not self.stack:
                        raise RuntimeError("Stack underflow when popping call arguments")
                    args.append(self.stack.pop())
                args.reverse()  # now args[0] is first parameter
                # push current frame
                self.call_stack.append((self.pc, self.locals))
                # set up callee frame
                self.locals = [0] * fn.num_locals
                for i, v in enumerate(args):
                    if i < len(self.locals):
                        self.locals[i] = v & 0xFFFF
                self.pc = fn.entry_pc

            elif op is OpCode.RET:
                # Pop return value (or 0 if none), restore caller frame, and push value for caller.
                ret_val = self.stack.pop() if self.stack else 0
                if not self.call_stack:
                    # return from main: use value as exit code
                    return ret_val
                ret_pc, prev_locals = self.call_stack.pop()
                self.locals = prev_locals
                self.stack.append(ret_val)
                self.pc = ret_pc

            elif op is OpCode.LOAD_LOCAL_IDX:
                idx = self.stack.pop()
                base = int(arg)
                self.stack.append(self.locals[base + idx])

            elif op is OpCode.STORE_LOCAL_IDX:
                # Stack order from codegen: [ ..., value, index ]
                idx = self.stack.pop()
                val = self.stack.pop()
                base = int(arg)
                if base + idx < 0 or base + idx >= len(self.locals):
                    raise RuntimeError(f"STORE_LOCAL_IDX out of range: base={base}, idx={idx}, num_locals={len(self.locals)}")
                self.locals[base + idx] = val

            elif op is OpCode.LOAD_INDIRECT:
                p = self.stack.pop()
                if p < 0 or p >= len(self.locals):
                    raise RuntimeError(f"LOAD_INDIRECT out of range: p={p}, num_locals={len(self.locals)}")
                self.stack.append(self.locals[p])

            elif op is OpCode.STORE_INDIRECT:
                v = self.stack.pop()
                p = self.stack.pop()
                if p < 0 or p >= len(self.locals):
                    raise RuntimeError(f"STORE_INDIRECT out of range: p={p}, num_locals={len(self.locals)}")
                self.locals[p] = v

            elif op is OpCode.MEMCPY_LOCALS:
                count = self.stack.pop()
                src = self.stack.pop()
                dst = self.stack.pop()
                if count < 0:
                    raise RuntimeError("MEMCPY_LOCALS negative count")
                for i in range(count):
                    si = src + i
                    di = dst + i
                    if si < 0 or si >= len(self.locals) or di < 0 or di >= len(self.locals):
                        raise RuntimeError(f"MEMCPY_LOCALS out of range: src={src}, dst={dst}, count={count}, num_locals={len(self.locals)}")
                    self.locals[di] = self.locals[si]

            elif op is OpCode.MEMSET_LOCALS:
                count = self.stack.pop()
                value = self.stack.pop()
                dst = self.stack.pop()
                if count < 0:
                    raise RuntimeError("MEMSET_LOCALS negative count")
                for i in range(count):
                    di = dst + i
                    if di < 0 or di >= len(self.locals):
                        raise RuntimeError(f"MEMSET_LOCALS out of range: dst={dst}, count={count}, num_locals={len(self.locals)}")
                    self.locals[di] = value

            elif op is OpCode.PRINT_INT:
                v = self.stack.pop()
                self._output(str(int(v)))

            elif op is OpCode.PRINT_STR:
                sid = self.stack.pop()
                s = self.strings.get(sid, "")
                self._output(s)

            elif op is OpCode.PRINTLN_INT:
                v = self.stack.pop()
                self._output(str(int(v)) + "\n")

            elif op is OpCode.PRINTLN_STR:
                sid = self.stack.pop()
                s = self.strings.get(sid, "")
                self._output(s + "\n")

            else:
                raise RuntimeError(f"Unknown opcode {op}")

        # fell off the end
        return 0
