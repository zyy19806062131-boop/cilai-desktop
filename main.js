'use strict';

const { app, BrowserWindow, Menu, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const http = require('node:http');

let mainWindow = null;
let pythonProcess = null;
const SERVER_PORT = 8765;

function findPython() {
  const candidates = [
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    '/usr/bin/python3'
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return 'python3';
}

function startPythonServer() {
  const serverScript = path.join(__dirname, 'server.py');
  const pythonBin = findPython();
  const env = {
    ...process.env,
    PATH: `/opt/homebrew/bin:/usr/local/bin:${process.env.PATH || ''}`
  };

  pythonProcess = spawn(pythonBin, [serverScript], {
    cwd: __dirname,
    env: env,
    stdio: 'ignore'
  });

  pythonProcess.on('error', (err) => {
    console.error('启动 Python 伴侣服务失败:', err);
  });
}

function stopPythonServer() {
  if (pythonProcess && !pythonProcess.killed) {
    try {
      pythonProcess.kill('SIGTERM');
    } catch (e) {}
    pythonProcess = null;
  }
}

function waitForServer(callback, maxAttempts = 60) {
  let attempts = 0;
  const check = () => {
    const req = http.get(`http://127.0.0.1:${SERVER_PORT}/api/status`, (res) => {
      if (res.statusCode === 200) {
        callback(true);
      } else {
        retry();
      }
    });
    req.on('error', () => retry());
    req.setTimeout(500, () => {
      req.destroy();
      retry();
    });
  };

  const retry = () => {
    attempts++;
    if (attempts < maxAttempts) {
      setTimeout(check, 150);
    } else {
      callback(false);
    }
  };

  check();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1240,
    height: 820,
    minWidth: 420,
    minHeight: 560,
    title: '词来 · 课堂生词速查与闪卡助手',
    backgroundColor: '#f8f6f2',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 18, y: 16 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  waitForServer((serverOk) => {
    if (serverOk) {
      mainWindow.loadURL(`http://127.0.0.1:${SERVER_PORT}/index.html`);
    } else {
      // 避免静默降级为 file:// 导致 localStorage 换仓丢失收藏，明确提示
      mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`
        <!DOCTYPE html><html><body style="font-family:sans-serif;padding:40px;background:#f8f6f2;color:#333;text-align:center;">
          <h2>本地服务启动超时 (8765端口)</h2>
          <p>请退出应用后重新打开，或检查端口是否被占用。</p>
        </body></html>
      `)}`);
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        shell.openExternal(url);
      }
    } catch (e) {}
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  startPythonServer();
  createWindow();

  app.on('activate', () => {
    if (!pythonProcess || pythonProcess.killed) {
      startPythonServer();
    }
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('will-quit', () => {
  stopPythonServer();
});

app.on('window-all-closed', () => {
  stopPythonServer();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
