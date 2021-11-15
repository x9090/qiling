#!/usr/bin/env python3
#
# Cross Platform and Multi Architecture Advanced Binary Emulation Framework
#

from __future__ import annotations
from typing import Callable, Optional, Mapping, Tuple, Union

import cmd

from qiling import Qiling
from qiling.const import QL_ARCH, QL_VERBOSE
from qiling.debugger import QlDebugger

from .frontend import context_reg, context_asm, examine_mem
from .utils import parse_int, handle_bnj, is_thumb, CODE_END
from .utils import Breakpoint, TempBreakpoint
from .const import *


class QlQdb(cmd.Cmd, QlDebugger):

    def __init__(self: QlQdb, ql: Qiling, init_hook: str = "", rr: bool = False) -> None:

        self.ql = ql
        self.prompt = f"{color.BOLD}{color.RED}Qdb> {color.END}"
        self._saved_reg_dump = None
        self.bp_list = {}
        self.rr = rr

        if self.rr:
            self._states_list = []

        super().__init__()

        self.cur_addr = self.ql.loader.entry_point

        self.do_start()
        self.interactive()

    @property
    def cur_addr(self: QlQdb) -> int:
        """
        getter for current address of qiling instance
        """

        return self.ql.reg.arch_pc

    @cur_addr.setter
    def cur_addr(self: QlQdb, address: int) -> None:
        """
        setter for current address of qiling instance
        """

        self.ql.reg.arch_pc = address

    def _bp_handler(self: QlQdb, *args) -> None:
        """
        internal function for handling once breakpoint hitted
        """

        if (bp := self.bp_list.get(self.cur_addr, None)):

            if isinstance(bp, TempBreakpoint):
                # remove TempBreakpoint once hitted
                self.del_breakpoint(bp)

            else:
                if bp.hitted:
                    return

                print(f"{color.CYAN}[+] hit breakpoint at 0x{self.cur_addr:08x}{color.END}")
                bp.hitted = True

            self.do_context()

    def _save(self: QlQdb, *args) -> None:
        """
        internal function for saving state of qiling instance
        """

        self._states_list.append(self.ql.save())

    def _restore(self: QlQdb, *args) -> None:
        """
        internal function for restoring state of qiling instance
        """

        self.ql.restore(self._states_list.pop())

    def _run(self: Qldbg, address: int = 0, count: int = 0) -> None:
        """
        internal function for emulating instruction
        """

        if not address:
            address = self.cur_addr

        if self.ql.archtype in (QL_ARCH.ARM, QL_ARCH.ARM_THUMB) and is_thumb(self.ql.reg.cpsr):
            address |= 1

        self.ql.emu_start(address, 0, count=count)

    def parseline(self: QlQdb, line: str) -> Tuple[Optional[str], Optional[str], str]:
        """
        Parse the line into a command name and a string containing
        the arguments.  Returns a tuple containing (command, args, line).
        'command' and 'args' may be None if the line couldn't be parsed.
        """

        line = line.strip()
        if not line:
            return None, None, line
        elif line[0] == '?':
            line = 'help ' + line[1:]
        elif line.startswith('!'):
            if hasattr(self, 'do_shell'):
                line = 'shell ' + line[1:]
            else:
                return None, None, line
        i, n = 0, len(line)
        while i < n and line[i] in self.identchars: i = i+1
        cmd, arg = line[:i], line[i:].strip()
        return cmd, arg, line

    def interactive(self: QlQdb, *args) -> None:
        """
        initial an interactive interface
        """

        return self.cmdloop()

    def run(self: QlQdb, *args) -> None:
        """
        internal command for running debugger
        """

        self._run()

    def emptyline(self: QlQdb, *args) -> None:
        """
        repeat last command
        """

        if (lastcmd := getattr(self, "do_" + self.lastcmd, None)):
            return lastcmd()

    def do_run(self: QlQdb, *args) -> None:
        """
        launching qiling instance
        """

        self._run()

    def do_context(self: QlQdb, *args) -> None:
        """
        show context information for current location
        """

        context_reg(self.ql, self._saved_reg_dump)
        context_asm(self.ql, self.cur_addr)

    def do_backward(self: QlQdb, *args) -> None:
        """
        step barkward if it's possible, option rr should be enabled and previous instruction must be executed before
        """

        if getattr(self, "_states_list", None) is None or len(self._states_list) == 0:
            print(f"{color.RED}[!] there is no way back !!!{color.END}")

        else:
            print(f"{color.CYAN}[+] step backward ~{color.END}")
            self._restore()
            self.do_context()

    def do_step(self: QlQdb, *args) -> Optional[bool, None]:
        """
        execute one instruction at a time
        """

        if self.ql is None:
            print(f"{color.RED}[!] The program is not being run.{color.END}")

        else:
            self._saved_reg_dump = dict(filter(lambda d: isinstance(d[0], str), self.ql.reg.save().items()))

            _, next_stop = handle_bnj(self.ql, self.cur_addr)

            if next_stop is CODE_END:
                return True

            if self.rr:
                self._save()

            count = 1
            if self.ql.archtype == QL_ARCH.MIPS and next_stop != self.cur_addr + 4:
                # make sure delay slot executed
                count = 2

            self._run(count=count)
            self.do_context()

    def set_breakpoint(self: QlQdb, address: int, is_temp: bool = False) -> None:
        """
        internal function for placing breakpoints
        """

        bp = TempBreakpoint(address) if is_temp else Breakpoint(address)

        bp.hook = self.ql.hook_address(self._bp_handler, address)

        self.bp_list.update({address: bp})

    def del_breakpoint(self: QlQdb, bp: Union[Breakpoint, TempBreakpoint]) -> None:
        """
        internal function for removing breakpoints
        """

        if self.bp_list.pop(bp.addr, None):
            bp.hook.remove()

    def do_start(self: QlQdb, address: str = "", *args) -> None:
        """
        move current context to ql.loader.entry_point
        """

        self.cur_addr = self.ql.loader.entry_point  # ld.so
        # self.cur_addr = self.ql.loader.elf_entry    # .text of binary

        # need a proper method for this
        # self.ql.restore(self._init_state)

        self.do_context()

    def do_breakpoint(self: QlQdb, address: str = "") -> None:
        """
        set breakpoint on specific address
        """

        address = parse_int(address) if address else self.cur_addr

        self.set_breakpoint(address)

        print(f"{color.CYAN}[+] Breakpoint at 0x{address:08x}{color.END}")

    def do_continue(self: QlQdb, address: str = "") -> None:
        """
        continue execution from current address if no specified 
        """

        if address:
            address = parse_int(address)

        print(f"{color.CYAN}continued from 0x{self.cur_addr:08x}{color.END}")
        self._run(address)

    def do_examine(self: QlQdb, line: str) -> None:
        """
        Examine memory: x/FMT ADDRESS.
        format letter: o(octal), x(hex), d(decimal), u(unsigned decimal), t(binary), f(float), a(address), i(instruction), c(char), s(string) and z(hex, zero padded on the left)
        size letter: b(byte), h(halfword), w(word), g(giant, 8 bytes)
        e.g. x/4wx 0x41414141 , print 4 word size begin from address 0x41414141 in hex
        """

        try:
            if not examine_mem(self.ql, line):
                self.do_help("examine")
        except:
            print(f"{color.RED}[!] something went wrong ...{color.END}")

    def do_show(self: QlQdb, *args) -> None:
        """
        show some runtime information
        """

        self.ql.mem.show_mapinfo()
        print(f"Breakpoints: {[hex(addr) for addr in self.bp_list.keys()]}")

    def do_disassemble(self: QlQdb, address: str, /, *args, **kwargs) -> None:
        """
        disassemble instructions from address specified
        """

        try:
            context_asm(self.ql, parse_int(address), 4)
        except:
            print(f"{color.RED}[!] something went wrong ...{color.END}")

    def do_shell(self: QlQdb, *command) -> None:
        """
        run python code
        """

        try:
            print(eval(*command))
        except:
            print("something went wrong ...")

    def do_quit(self: QlQdb, *args) -> bool:
        """
        exit Qdb and stop running qiling instance
        """

        self.ql.stop()
        exit()

    do_r = do_run
    do_s = do_step
    do_q = do_quit
    do_x = do_examine
    do_p = do_backward
    do_c = do_continue
    do_b = do_breakpoint
    do_dis = do_disassemble


if __name__ == "__main__":
    pass
