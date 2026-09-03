'use strict';

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..');
const distDir = path.join(repoRoot, 'dist');
const appPath = path.join(distDir, '词来-darwin-arm64', '词来.app');
const stagingDir = path.join(distDir, 'dmg_staging');
const outputDmg = path.join(distDir, '词来-1.0.0-macOS-arm64.dmg');

if (!fs.existsSync(appPath)) {
  console.error(`找不到构建出的应用：${appPath}，请先执行 npm run package:mac`);
  process.exit(1);
}

console.log('正在构建 macOS 一键安装镜像 (.dmg)...');

if (fs.existsSync(stagingDir)) {
  fs.rmSync(stagingDir, { recursive: true, force: true });
}
fs.mkdirSync(stagingDir, { recursive: true });

// 拷贝应用到 staging
const stagedApp = path.join(stagingDir, '词来.app');
spawnSync('cp', ['-R', appPath, stagedApp], { stdio: 'inherit' });

// 建立 /Applications 软连接
fs.symlinkSync('/Applications', path.join(stagingDir, 'Applications'));

// 删除旧 dmg
if (fs.existsSync(outputDmg)) {
  fs.unlinkSync(outputDmg);
}

// 调用系统 hdiutil 生成标准压缩镜像
const result = spawnSync('hdiutil', [
  'create',
  '-volname', '词来',
  '-srcfolder', stagingDir,
  '-ov',
  '-format', 'UDZO',
  outputDmg
], { stdio: 'inherit' });

// 清理 staging
fs.rmSync(stagingDir, { recursive: true, force: true });

if (result.status !== 0) {
  console.error('构建 DMG 失败');
  process.exit(result.status);
}

const stats = fs.statSync(outputDmg);
console.log(`✅ DMG 一键安装包生成成功：${outputDmg}`);
console.log(`📦 体积大小：${(stats.size / (1024 * 1024)).toFixed(1)} MB`);
