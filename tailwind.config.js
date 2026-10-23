/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./ui/**/*.html",
        "./ui/**/*.js"
    ],
    theme: {
        extend: {
            colors: {
                ink: "#2B2540",
                violet: "#4B36A8",
                "violet-2": "#5E4E9E",
                header: "#7A5FE0",
                "header-sh": "#3A2790",
                bezel: "#C9BCF5",
                "bezel-sh": "#A995EE",
                ring: "#8F78EA",
                pinkbz: "#F7B3D8",
                "pinkbz-sh": "#EE8DC2",
                "pink-soft": "#F9C6E4",
                accent: "#D6338C",
                hot: "#F25AAE",
                sky: "#9FD4F7",
                mint: "#BFF0D4",
                "mint-bd": "#4CB97E",
                "mint-ink": "#12502F",
                paper: "#FBFAFF",
                soft: "#F4F0FE",
                chip: "#EEE9FD",
                line: "#CFC3F6",
                warn: "#FFF1C2",
                "warn-bd": "#E0A800",
                "warn-ink": "#6B4A00",
                err: "#FFE0EE",
                "err-ink": "#A3245F",
                note: "#FFF6B8"
            },
            fontFamily: {
                sans: ["'IBM Plex Sans Thai'", "system-ui", "sans-serif"],
                dela: ["'Dela Gothic One'", "'IBM Plex Sans Thai'", "sans-serif"],
                sil: ["'Silkscreen'", "'IBM Plex Mono'", "monospace"],
                mono: ["'IBM Plex Mono'", "monospace"]
            }
        }
    },
    plugins: []
};