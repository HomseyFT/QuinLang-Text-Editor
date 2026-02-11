; QuinLang runtime include for NASM
%include "runtime/abi.inc"

; Bring in CRT and runtime routines
%include "runtime/crt0_com.asm"
%include "runtime/num.asm"
%include "runtime/str.asm"
