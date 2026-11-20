/* padheck.ld - the pinHeck mode runtime in a game's free flash (build.sh; hooks.py).
 * PAD_FLASH / PAD_RAM_AT come from the build's hook table (--defsym). */
ENTRY(pad_entry)
SECTIONS
{
    . = PAD_FLASH;
    .head : { KEEP(*(.head)) }
    .text : { *(.text.entry) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.* .sdata .sdata.*) }
    .bss : { *(.bss .bss.* .sbss .sbss.* COMMON) }
    . = ALIGN(256);
    PAD_DATA = .;
    PAD_RUN = PAD_RAM_AT;
    ASSERT(SIZEOF(.data) == 0, "padheck: no initialised variables (no start-up code runs them)")
    ASSERT(SIZEOF(.bss) == 0, "padheck: every variable lives in struct run (PAD_RUN)")
    /DISCARD/ : { *(.reginfo) *(.MIPS.*) *(.pdr) *(.comment) *(.gnu.*) *(.note*) *(.eh_frame*) }
}
