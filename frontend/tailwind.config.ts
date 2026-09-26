import type { Config } from "tailwindcss";

/**
 * Design tokens ported from the ui/ design prototype.
 * Names describe role, not appearance, so a theme change does not rename everything.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          base: "#0A0B0D",
          raised: "#0E1013",
          inset: "#101317",
          hover: "#15181C",
          overlay: "rgba(6,7,9,0.95)",
        },
        line: {
          DEFAULT: "#1D2126",
          strong: "#23272D",
          subtle: "#16191E",
          faint: "#1A1D22",
        },
        ink: {
          DEFAULT: "#E8EAED",
          muted: "#9BA2AB",
          dim: "#8A9099",
          faint: "#7D848D",
          ghost: "#6E757E",
          trace: "#5E656D",
        },
        accent: {
          DEFAULT: "#E8112D",
          bright: "#FF2A42",
          soft: "#FF6A6A",
        },
        /** Semantic status colours. Never the only signal — always paired with a label. */
        status: {
          ready: "#00D68F",
          pending: "#FFB800",
          idle: "#3A4049",
        },
        compound: {
          soft: "#E8112D",
          medium: "#FFC400",
          hard: "#D8DCE1",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "Titillium Web", "system-ui", "sans-serif"],
        body: ["var(--font-body)", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "ui-monospace", "monospace"],
      },
      keyframes: {
        pulse: {
          "0%,100%": { opacity: "0.5", transform: "scale(0.9)" },
          "50%": { opacity: "1", transform: "scale(1.04)" },
        },
        sweep: {
          "0%": { transform: "translateX(-120%)" },
          "100%": { transform: "translateX(420%)" },
        },
        rise: {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "none" },
        },
        fade: { from: { opacity: "0" }, to: { opacity: "1" } },
        bar: { from: { transform: "scaleX(0)" }, to: { transform: "scaleX(1)" } },
        drift: {
          from: { backgroundPosition: "0 0" },
          to: { backgroundPosition: "0 -36px" },
        },
      },
      animation: {
        pulse: "pulse 1.15s ease-in-out infinite",
        "pulse-slow": "pulse 1.6s ease-in-out infinite",
        sweep: "sweep 3.4s ease-in-out infinite",
        "sweep-fast": "sweep 2.2s linear infinite",
        rise: "rise 0.4s ease both",
        fade: "fade 0.4s ease both",
        bar: "bar 0.7s cubic-bezier(.2,.8,.2,1) both",
        drift: "drift 2.4s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
