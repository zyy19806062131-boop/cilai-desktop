#!/usr/bin/env node
'use strict';

const ci = require('miniprogram-ci');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const APPID = 'wxe21b5b29a8191b29';
const projectPath = __dirname;

function findPrivateKey() {
  const candidates = [
    path.join(os.homedir(), '.config', 'gamekit', `private.${APPID}.key`),
    path.join(os.homedir(), '.config', 'gamekit', 'private.key'),
    path.join(projectPath, 'private.key'),
    path.join(projectPath, `private.${APPID}.key`)
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return null;
}

async function main() {
  const args = process.argv.slice(2);
  const command = args[0] || 'preview';
  const version = args[1] || '1.0.0';
  const desc = args[2] || `更新于 ${new Date().toLocaleString('zh-CN')}`;

  const keyPath = findPrivateKey();
  if (!keyPath) {
    console.error('========================================================');
    console.error('❌ 未找到「小程序代码上传密钥」！');
    console.error('');
    console.error('请去微信公众平台后台下载密钥并放置在：');
    console.error(`~/.config/gamekit/private.${APPID}.key`);
    console.error('');
    console.error('获取步骤：');
    console.error('1. 登录 mp.weixin.qq.com -> 进入「开发」->「开发管理」->「开发设置」');
    console.error('2. 找到「小程序代码上传密钥」-> 点击「生成」并下载 .key 文件');
    console.error('3. 记得关闭「IP白名单」（或将本机IP加入白名单）');
    console.error('========================================================');
    process.exit(1);
  }

  console.log(`✓ 已找到上传密钥: ${keyPath}`);
  console.log(`正在初始化 miniprogram-ci (AppID: ${APPID})...`);

  const project = new ci.Project({
    appid: APPID,
    type: 'miniProgram',
    projectPath: projectPath,
    privateKeyPath: keyPath,
    ignores: ['node_modules/**/*', 'private*.key', '.git/**/*']
  });

  if (command === 'upload') {
    console.log(`正在上传代码至微信后台 (版本号: ${version}, 描述: ${desc})...`);
    try {
      const uploadResult = await ci.upload({
        project,
        version,
        desc,
        setting: {
          es6: true,
          es7: true,
          minify: true,
          autoPrefixWXSS: true
        },
        onProgressUpdate: console.log
      });
      console.log('✅ 上传成功！上传结果:', uploadResult);
      console.log('现在可直接去微信后台提交审核或在体验版里体验！');
    } catch (err) {
      console.error('❌ 上传失败:', err);
      process.exit(1);
    }
  } else if (command === 'preview') {
    const qrcodeDest = path.join(projectPath, 'preview_qrcode.jpg');
    console.log(`正在生成真机预览二维码...`);
    try {
      const previewResult = await ci.preview({
        project,
        desc,
        setting: {
          es6: true,
          es7: true,
          minify: true,
          autoPrefixWXSS: true
        },
        qrcodeFormat: 'image',
        qrcodeOutputDest: qrcodeDest,
        onProgressUpdate: console.log
      });
      console.log(`✅ 预览二维码已生成！保存至: ${qrcodeDest}`);
      console.log(previewResult);
    } catch (err) {
      console.error('❌ 生成预览失败:', err);
      process.exit(1);
    }
  } else {
    console.log('用法:');
    console.log('  node ci.js preview                    # 生成真机预览二维码');
    console.log('  node ci.js upload 1.0.0 "更新描述"     # 命令行一键上传到微信后台');
  }
}

main().catch(console.error);
