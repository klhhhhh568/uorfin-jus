const { ipcRenderer } = require('electron');

document.getElementById('installBtn').addEventListener('click', () => {
    const lang = document.getElementById('lang').value;
    const autostart = document.getElementById('autostart').checked;
    const desktop = document.getElementById('desktop').checked;

    ipcRenderer.send('install-settings', { lang, autostart, desktop });
});