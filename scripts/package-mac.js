'use strict';

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const appRoot = path.resolve(__dirname, '..');
const packager = path.resolve(
  appRoot,
  '..',
  '..',
  'repos',
  'yomi-desktop-pet',
  'node_modules',
  '@electron',
  'packager',
  'bin',
  'electron-packager.mjs'
);

if (!fs.existsSync(packager)) {
  console.error(`找不到 Electron Packager：${packager}`);
  process.exit(1);
}

console.log('正在打包「词来」桌面应用 (macOS arm64)...');

const result = spawnSync(process.execPath, [
  packager,
  appRoot,
  '词来',
  '--platform=darwin',
  '--arch=arm64',
  '--electron-version=42.4.0',
  '--out=dist',
  '--overwrite',
  '--no-asar',
  '--prune=true',
  '--app-bundle-id=local.yiyue.cilai',
  '--ignore=^/dist($|/)',
], { cwd: appRoot, stdio: 'inherit' });

if (result.status !== 0) {
  console.error('打包失败，退出码:', result.status);
  process.exit(result.status);
}

// 替换应用图标
const iconset = path.join(appRoot, 'build', 'icon.icns');
const bundled = path.join(
  appRoot,
  'dist',
  '词来-darwin-arm64',
  '词来.app',
  'Contents',
  'Resources',
  'electron.icns'
);

if (fs.existsSync(iconset) && fs.existsSync(bundled)) {
  fs.copyFileSync(iconset, bundled);
  console.log(`已应用 3D C4D 应用图标 → ${bundled}`);
}

// 安装到桌面并清理旧名「Preply词卡.app」
const builtApp = path.join(appRoot, 'dist', '词来-darwin-arm64', '词来.app');
const desktopApp = path.join(os.homedir(), 'Desktop', '词来.app');
const legacyApp = path.join(os.homedir(), 'Desktop', 'Preply词卡.app');

if (fs.existsSync(builtApp)) {
  fs.rmSync(desktopApp, { recursive: true, force: true });
  fs.cpSync(builtApp, desktopApp, { recursive: true, verbatimSymlinks: true });
  console.log(`📦 成功安装到桌面：${desktopApp}`);
  
  if (fs.existsSync(legacyApp)) {
    fs.rmSync(legacyApp, { recursive: true, force: true });
    console.log(`🧹 已清理桌面旧应用副本：${legacyApp}`);
  }
}

console.log('✅ 打包与桌面部署完成！');
