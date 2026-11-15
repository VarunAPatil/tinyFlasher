#include <stdint.h>

/* ESP32-S3 TRM v1.8, USB Serial/JTAG chapter: base 0x60038000. */
#define USB_FIFO (*(volatile uint32_t *)0x60038000u)
#define USB_CONF (*(volatile uint32_t *)0x60038004u)
#define USB_WR_DONE (1u << 0)
#define USB_IN_FREE (1u << 1)

/* ROM flash boot leaves both flash-boot watchdogs running. */
#define TG0_WDT_CFG (*(volatile uint32_t *)0x6001f048u)
#define TG0_WDT_KEY (*(volatile uint32_t *)0x6001f064u)
#define RTC_WDT_CFG (*(volatile uint32_t *)0x60008098u)
#define RTC_WDT_KEY (*(volatile uint32_t *)0x600080b0u)
#define RTC_SWD_CFG (*(volatile uint32_t *)0x600080b4u)
#define RTC_SWD_KEY (*(volatile uint32_t *)0x600080b8u)
#define SYSCLK_CONF (*(volatile uint32_t *)0x600c0060u)

static void finish_rom_boot(void)
{
    TG0_WDT_KEY = 0x50d83aa1u;
    TG0_WDT_CFG = 0; /* Clear flash-boot mode and watchdog enable. */
    TG0_WDT_KEY = 0;
    RTC_WDT_KEY = 0x50d83aa1u;
    RTC_WDT_CFG = 0;
    RTC_WDT_KEY = 0;
    RTC_SWD_KEY = 0x8f1d312au;
    RTC_SWD_CFG |= 1u << 30; /* Minimal demo has no super-WDT service loop. */
    RTC_SWD_KEY = 0;

    /* ROM defaults to XTAL / 2 = 20 MHz. USB needs APB >= 40 MHz. */
    if (((SYSCLK_CONF >> 10) & 3u) == 0u)
        SYSCLK_CONF &= ~0x3ffu; /* XTAL / 1 = 40 MHz. */
}

static void usb_write(const char *s)
{
    for (; *s; ++s) {
        unsigned timeout = 1000000;
        while (!(USB_CONF & USB_IN_FREE) && --timeout) { }
        if (!timeout) return; /* USB host is absent or not reading. */
        USB_FIFO = (uint8_t)*s;
    }
    USB_CONF = USB_WR_DONE; /* Short packets need an explicit flush. */
}

int main(void)
{
    finish_rom_boot();
    for (;;) {
        usb_write("Hello, world from ESP32-S3 USB Serial/JTAG!\r\n");
        for (volatile uint32_t delay = 0; delay < 10000000u; ++delay) { }
    }
}
