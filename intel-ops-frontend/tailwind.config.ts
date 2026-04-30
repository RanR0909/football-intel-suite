import type { Config } from "tailwindcss"

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // shadcn semantic（与 index.css CSS 变量绑定）
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        border: "hsl(var(--border))",
        "border-soft": "hsl(var(--border-soft))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // 主色：AF 官网绿
        brand: {
          50: "#E6FBE9",
          100: "#C2F5C9",
          200: "#8AEC97",
          300: "#4FE065",
          400: "#1FD43A",
          500: "#00D616",
          600: "#00B011",
          700: "#008A0D",
          800: "#006308",
          900: "#003D05",
        },
        semantic: {
          success: "#1D9E75",
          warning: "#EF9F27",
          danger: "#E24B4A",
          info: "#185FA5",
        },
        pill: {
          purple: { bg: "#EEEDFE", fg: "#26215C" },
          teal: { bg: "#E1F5EE", fg: "#04342C" },
          amber: { bg: "#FAEEDA", fg: "#412402" },
          blue: { bg: "#E6F1FB", fg: "#042C53" },
          pink: { bg: "#FBEAF0", fg: "#4B1528" },
          red: { bg: "#FCEBEB", fg: "#501313" },
          green: { bg: "#EAF3DE", fg: "#173404" },
          gray: { bg: "#F4F3F0", fg: "#5F5E5A" },
        },
      },
      fontFamily: {
        sans: ["Geist", "system-ui", "PingFang SC", "Microsoft YaHei", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["10px", "1.4"],
        xs: ["11px", "1.5"],
        sm: ["12px", "1.5"],
        base: ["13px", "1.55"],
        lg: ["14px", "1.5"],
        xl: ["16px", "1.4"],
        "2xl": ["18px", "1.35"],
        "3xl": ["22px", "1.3"],
      },
      borderRadius: {
        sm: "4px",
        md: "6px",
        lg: "10px",
      },
      borderWidth: {
        DEFAULT: "0.5px",
      },
      spacing: {
        "0.25": "1px",
        "0.5": "2px",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config
