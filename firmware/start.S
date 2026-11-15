.section .text.start, "ax"
.global _start
.type _start, @function
_start:
    /* The ROM jumps here after loading the image. Give C its own stack. */
    movi a1, 0x3fc98000
    call0 main
1:  j 1b
