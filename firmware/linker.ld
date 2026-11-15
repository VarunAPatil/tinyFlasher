ENTRY(_start)

SECTIONS
{
    /* ROM-loaded code and literals in instruction SRAM. */
    . = 0x40378000;
    .iram : ALIGN(4) {
        *(.literal .literal.*)
        *(.text.start)
        *(.text .text.*)
    }

    /* ROM-loaded constants in data SRAM. Stack starts above this area. */
    . = 0x3fc90000;
    .dram : ALIGN(4) {
        *(.rodata .rodata.*)
        *(.data .data.*)
    }
    .bss (NOLOAD) : ALIGN(4) { *(.bss .bss.* COMMON) }
}
ASSERT(SIZEOF(.bss) == 0, "This tiny runtime does not initialize BSS")
ASSERT(SIZEOF(.dram) < 0x8000, "Data overlaps the stack")
