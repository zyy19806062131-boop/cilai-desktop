'use strict';

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const appRoot = path.resolve(__dirname, '..');
const electronCLI = path.resolve(
  appRoot,
  '..',
  '..',
  'repos',
  'yomi-desktop-pet',
  'node_modules',
  'electron',
  'cli.js'
);

if (!fs.existsSync(electronCLI)) {
  console.error(`找不到 Electron CLI：${electronCLI}`);
  process.exit(1);
}

const child = spawn(process.execPath, [electronCLI, appRoot], {
  cwd: appRoot,
  stdio: 'inherit'
});

child.on('exit', (code) => {
  process.exit(code ?? 0);
});
