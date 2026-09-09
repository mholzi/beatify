import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['custom_components/beatify/www/js/__tests__/**/*.test.js'],
    environment: 'node',
    coverage: {
      // Coverage is opt-in via `npm run test:coverage` (and CI). The gate below
      // is a *floor* set well under the currently-measured numbers (#1582) so it
      // can only catch a regression, never flake CI on a small delta.
      provider: 'v8',
      reporter: ['text-summary', 'html'],
      include: ['custom_components/beatify/www/js/**/*.js'],
      exclude: [
        '**/__tests__/**',
        'custom_components/beatify/www/js/vendor/**',
        '**/*.min.js',
      ],
      thresholds: {
        // Neu geeicht am 09.09.2026 beim Sprung vitest 2.1.9 -> 5.0.0 (#2580).
        //
        // **Die Zahlen sind kleiner geworden, die Abdeckung nicht.** v8 zaehlt
        // in vitest 5 anders, und zwar in beide Richtungen — gemessen an
        // demselben Code, am selben Tag, ohne eine Zeile Aenderung:
        //
        //              vitest 2.1.9          vitest 5.0.0
        //   Statements 44,14 % (14936/33832)  32,18 % (4909/15254)
        //   Branches   67,78 % ( 2041/ 3011)  26,73 % (3106/11617)
        //   Functions  54,40 % (  513/  943)  34,05 % ( 723/ 2123)
        //
        // Man sieht es an den Nennern, nicht an den Prozenten: die Zahl der
        // gezaehlten Verzweigungen steigt von 3011 auf 11617, die der
        // Anweisungen faellt von 33832 auf 15254. Wer nur auf „67,78 -> 26,73"
        // schaut, liest eine Katastrophe, wo eine andere Messlatte steht.
        //
        // Die Schwellen sind deshalb gegen die NEUE Zaehlung gesetzt, mit
        // demselben Abstand wie vorher: ein paar Punkte unter dem Messwert, um
        // v8-Rauschen abzufangen, aber nah genug, um einen echten Rueckgang zu
        // fangen. Wer sie das naechste Mal anfasst, misst zuerst und schreibt
        // die Messung dazu.
        lines: 28,
        statements: 28,
        functions: 28,
        branches: 22,
      },
    },
  },
});
