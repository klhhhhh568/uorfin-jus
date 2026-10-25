# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

block_cipher = None

# Корень проекта (выше папки web)
PROJECT_ROOT = os.path.abspath(os.path.join(os.getcwd(), '..'))

# ============ ДАННЫЕ ============
datas = []
binaries = []   # ← обязательно! Объявлено до использования

def add_data(src_dir, dest_dir):
    full_path = os.path.join(PROJECT_ROOT, src_dir)
    if os.path.exists(full_path):
        datas.append((full_path, dest_dir))
        print(f"✅ Добавлен ресурс: {src_dir} -> {dest_dir}")
    else:
        print(f"⚠️ Пропущен (не найден): {src_dir}")

add_data('web/templates', 'templates')
add_data('web/static', 'static')
add_data('skills', 'skills')
add_data('output', 'output')
add_data('gcode', 'gcode')

# Копируем picogk_binding.py
add_data('skills/picogk_binding.py', 'skills')

# uorfin_charter.yaml в корень
charter_file = os.path.join(PROJECT_ROOT, 'uorfin_charter.yaml')
if os.path.isfile(charter_file):
    datas.append((charter_file, '.'))
    print("✅ Добавлен uorfin_charter.yaml в корень сборки")
else:
    with open(charter_file, 'w', encoding='utf-8') as f:
        f.write('')
    datas.append((charter_file, '.'))

# ============ HIDDENIMPORTS ============
hiddenimports = [
    # --- Flask / SocketIO ---
    'flask',
    'flask_socketio',
    'flask_cors',
    'engineio',
    'engineio.async_drivers',
    'engineio.async_drivers.threading',
    'engineio.async_drivers._websocket_wsgi',
    'socketio',
    'socketio.async_handlers',
    'socketio.async_manager',
    'socketio.async_namespace',
    'socketio.async_pubsub_manager',
    'socketio.async_server',
    'socketio.async_simple_client',

    # --- Тримеш / геометрия ---
    'trimesh',
    'trimesh.exchange',
    'trimesh.exchange.stl',
    'trimesh.ray',
    'trimesh.path',
    'trimesh.primitives',
    'trimesh.visual',
    'trimesh.voxel',
    'numpy',
    'scipy',
    'scipy.sparse',
    'scipy.sparse.csgraph',
    'shapely',
    'rtree',
    'networkx',

    # --- Сеть / утилиты ---
    'requests',
    'urllib3',
    'charset_normalizer',
    'idna',
    'certifi',
    'yaml',
    'psutil',
    'json',
    'pickle',

    # --- OpenKLHCAD (только то, что используем) ---
    'openklhcad',
    'openklhcad.triz',
    'openklhcad.triz.calculator',
    'openklhcad.triz.contradictions',
    'openklhcad.triz.principles',
    'openklhcad.llm',
    'openklhcad.llm.prompt_analyzer',
    'openklhcad.llm.shape_recognizer',

    # --- numpy-stl ---
    'stl',
    'stl.mesh',

    # --- PicoGK ---
    'skills.picogk_binding',
    'ctypes',
    'ctypes.util',
    'struct',

    # --- Навыки ---
    'skills',
    'skills.printer_skill',
    'skills.slicer_skill',
    'skills.ros_bridge',
    'skills.ros2_skill',
    'skills.cad_generation',
    'skills.prompt_extractor',
    'skills.triz_skill',
    'skills.cerebellum_skill',
    'skills.dual_hemisphere_cloud',
    'skills.memory_skill',
    'skills.ollama_client',
    'skills.orchestrator_skill',
    'skills.llm_skill',
    'skills.charter_skill',
    'skills.council_skill',
    'skills.hello_skill',
    'skills.brain_db',
    'skills.neural_engine',
    'skills.brain_bootstrap',
    'skills.picogk_worker',

    # --- Стандартные ---
    'dataclasses',
    'typing',
    'serial',
    'serial.tools',
    'serial.tools.list_ports',
]

# ============ АНАЛИЗ ============
a = Analysis(
    ['web_server.py'],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyd = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_name = 'run_backend'
if sys.platform == 'win32':
    exe_name += '.exe'

exe = EXE(
    pyd,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)