'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  isElectron: true,
  platform: process.platform,
  /* 2026-09-03 加（小克，老师报「一键导出 HTML 是假功能」）：
     渲染层原来用 <a download> + blob 存文件。Electron 里这条路要么被吞、
     要么静默存到某个地方，界面还弹一句"已下载"——老师看不到文件，就是假功能。
     改成走主进程：弹系统保存框、真写盘、把真实路径回传，提示里报路径。 */
  saveFile: (name, content) => ipcRenderer.invoke('cilai:save-file', { name, content }),
  showInFolder: (p) => ipcRenderer.invoke('cilai:show-in-folder', p)
});
