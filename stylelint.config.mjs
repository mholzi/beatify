/**
 * Stylelint (#3387): hard-coded colours and sizes outside the token file.
 *
 * Warning only, on purpose. styles.css still carries well over a thousand
 * literal colours; the design-system migration moves them onto tokens step by
 * step, and the CI step reports the count without failing the build. Raise the
 * severity to "error" once the migration plan's last step lands.
 *
 * tokens.css is the one place where literal values belong, so it is ignored.
 */
export default {
  defaultSeverity: "warning",
  plugins: ["stylelint-declaration-strict-value"],
  ignoreFiles: [
    "custom_components/beatify/www/**/*.min.css",
    "custom_components/beatify/www/css/tokens.css",
  ],
  rules: {
    "color-no-hex": true,
    "color-named": "never",
    "scale-unlimited/declaration-strict-value": [
      ["/color$/", "background", "fill", "stroke", "font-size", "border-radius", "box-shadow"],
      {
        ignoreValues: [
          "transparent",
          "currentColor",
          "currentcolor",
          "inherit",
          "initial",
          "unset",
          "none",
          "0",
        ],
        ignoreFunctions: false,
        disableFix: true,
      },
    ],
  },
};
