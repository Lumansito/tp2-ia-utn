const { run } = require('@softwaretechnik/dbml-renderer');
const fs = require('fs');

const inputFile = process.argv[2];
const outputFile = process.argv[3];

if (!inputFile) {
  console.error("Uso: node render_dbml.js <input.dbml> [output.svg]");
  process.exit(1);
}

try {
  const dbml = fs.readFileSync(inputFile, 'utf-8');
  const svg = run(dbml, 'svg');
  if (outputFile) {
    fs.writeFileSync(outputFile, svg, 'utf-8');
    console.log("SVG generado exitosamente en " + outputFile);
  } else {
    process.stdout.write(svg);
  }
} catch (err) {
  console.error("Error al renderizar DBML:", err.message);
  process.exit(1);
}
