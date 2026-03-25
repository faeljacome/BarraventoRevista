const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const requirementsPath = path.join(ROOT, "requirements.txt");

if (!fs.existsSync(requirementsPath)) {
  console.log("requirements.txt nao encontrado. Nenhuma dependencia Python para instalar.");
  process.exit(0);
}

const commands = process.platform === "win32"
  ? [
      ["py", ["-3", "-m", "pip", "install", "-r", requirementsPath]],
      ["python", ["-m", "pip", "install", "-r", requirementsPath]]
    ]
  : [
      ["python3", ["-m", "pip", "install", "-r", requirementsPath]],
      ["python", ["-m", "pip", "install", "-r", requirementsPath]]
    ];

let lastFailure = null;
for (const [command, args] of commands) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    stdio: "inherit"
  });
  if (!result.error && result.status === 0) {
    console.log(`Dependencias Python instaladas com ${command}.`);
    process.exit(0);
  }
  lastFailure = result.error || new Error(`Falha ao executar ${command} ${args.join(" ")}`);
}

console.error("Nao foi possivel instalar as dependencias Python do projeto.");
console.error(lastFailure ? String(lastFailure.message || lastFailure) : "Falha desconhecida.");
process.exit(1);
