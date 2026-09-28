'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  isElectron: true,
  platform: process.platform,
  saveImage: (name, dataUrl) => ipcRenderer.invoke('cilai:save-image', { name, dataUrl }),
  showInFolder: (p) => ipcRenderer.invoke('cilai:show-in-folder', p)
});
