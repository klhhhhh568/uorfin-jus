# skills/picogk_binding.py
# -*- coding: utf-8 -*-
"""
Python ctypes-обёртка для PicoGK C API.
Прямой вызов libpicogk.so — без C#, без посредников.
"""
import ctypes
import struct
import logging
import os
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

_picogk = None


# ============================================================
# ЗАГРУЗКА БИБЛИОТЕКИ
# ============================================================
def _load_library():
    global _picogk
    if _picogk is not None:
        return _picogk

    paths = [
        "libpicogk.so",                      # через ldconfig
        "/usr/local/lib/libpicogk.so",       # наш симлинк
        "/usr/local/lib/picogk.so",          # оригинал
    ]
    for p in paths:
        try:
            _picogk = ctypes.CDLL(p)
            logger.info(f"✅ PicoGK загружен: {p}")
            return _picogk
        except OSError:
            continue

    logger.error("❌ Не удалось загрузить libpicogk.so")
    return None


# ============================================================
# СТРУКТУРЫ (соответствуют PicoGKApiTypes.h)
# ============================================================
class PKVector3(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("z", ctypes.c_float),
    ]

    def __repr__(self):
        return f"({self.x:.2f}, {self.y:.2f}, {self.z:.2f})"


class PKVector2(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float)]


class PKVector4(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("z", ctypes.c_float),
        ("w", ctypes.c_float),
    ]


class PKBBox3(ctypes.Structure):
    _fields_ = [("vecMin", PKVector3), ("vecMax", PKVector3)]


class PKTriangle(ctypes.Structure):
    _fields_ = [
        ("A", ctypes.c_int32),
        ("B", ctypes.c_int32),
        ("C", ctypes.c_int32),
    ]


# ============================================================
# ПРОТОТИПЫ ФУНКЦИЙ
# ============================================================
PKHANDLE = ctypes.c_uint64


def _init_prototypes(lib):
    # ---- Library ----
    lib.Library_hCreateInstance.argtypes = [ctypes.c_float]
    lib.Library_hCreateInstance.restype = PKHANDLE

    lib.Library_DestroyInstance.argtypes = [PKHANDLE]
    lib.Library_DestroyInstance.restype = None

    lib.Library_GetVersion.argtypes = [ctypes.c_char_p]
    lib.Library_GetVersion.restype = None

    lib.Library_GetName.argtypes = [ctypes.c_char_p]
    lib.Library_GetName.restype = None

    lib.Library_MmToVoxels.argtypes = [
        PKHANDLE, ctypes.POINTER(PKVector3), ctypes.POINTER(PKVector3)
    ]
    lib.Library_MmToVoxels.restype = None

    lib.Library_VoxelsToMm.argtypes = [
        PKHANDLE, ctypes.POINTER(PKVector3), ctypes.POINTER(PKVector3)
    ]
    lib.Library_VoxelsToMm.restype = None

    # ---- Voxels ----
    lib.Voxels_hCreate.argtypes = [PKHANDLE, ctypes.c_float]
    lib.Voxels_hCreate.restype = PKHANDLE

    lib.Voxels_hCreateSphere.argtypes = [
        PKHANDLE, ctypes.POINTER(PKVector3), ctypes.c_float
    ]
    lib.Voxels_hCreateSphere.restype = PKHANDLE

    lib.Voxels_hCreateCapsule.argtypes = [
        PKHANDLE,
        ctypes.POINTER(PKVector3), ctypes.POINTER(PKVector3),
        ctypes.c_float, ctypes.c_float,
    ]
    lib.Voxels_hCreateCapsule.restype = PKHANDLE

    lib.Voxels_hCreateCopy.argtypes = [PKHANDLE, PKHANDLE]
    lib.Voxels_hCreateCopy.restype = PKHANDLE

    lib.Voxels_BoolAdd.argtypes = [PKHANDLE, PKHANDLE, PKHANDLE]
    lib.Voxels_BoolAdd.restype = None

    lib.Voxels_BoolSubtract.argtypes = [PKHANDLE, PKHANDLE, PKHANDLE]
    lib.Voxels_BoolSubtract.restype = None

    lib.Voxels_BoolIntersect.argtypes = [PKHANDLE, PKHANDLE, PKHANDLE]
    lib.Voxels_BoolIntersect.restype = None

    lib.Voxels_Offset.argtypes = [PKHANDLE, PKHANDLE, ctypes.c_float]
    lib.Voxels_Offset.restype = None

    lib.Voxels_DoubleOffset.argtypes = [
        PKHANDLE, PKHANDLE, ctypes.c_float, ctypes.c_float
    ]
    lib.Voxels_DoubleOffset.restype = None

    lib.Voxels_fCalculateVolume.argtypes = [PKHANDLE, PKHANDLE]
    lib.Voxels_fCalculateVolume.restype = ctypes.c_float

    lib.Voxels_fVoxelSize.argtypes = [PKHANDLE, PKHANDLE]
    lib.Voxels_fVoxelSize.restype = ctypes.c_float

    lib.Voxels_bIsValid.argtypes = [PKHANDLE, PKHANDLE]
    lib.Voxels_bIsValid.restype = ctypes.c_bool

    lib.Voxels_bIsEmpty.argtypes = [PKHANDLE, PKHANDLE]
    lib.Voxels_bIsEmpty.restype = ctypes.c_bool

    lib.Voxels_Destroy.argtypes = [PKHANDLE, PKHANDLE]
    lib.Voxels_Destroy.restype = None

    # ---- Mesh ----
    lib.Mesh_hCreate.argtypes = [PKHANDLE]
    lib.Mesh_hCreate.restype = PKHANDLE

    lib.Mesh_hCreateFromVoxels.argtypes = [PKHANDLE, PKHANDLE]
    lib.Mesh_hCreateFromVoxels.restype = PKHANDLE

    lib.Mesh_nTriangleCount.argtypes = [PKHANDLE, PKHANDLE]
    lib.Mesh_nTriangleCount.restype = ctypes.c_int32

    lib.Mesh_nVertexCount.argtypes = [PKHANDLE, PKHANDLE]
    lib.Mesh_nVertexCount.restype = ctypes.c_int32

    lib.Mesh_GetVertex.argtypes = [
        PKHANDLE, PKHANDLE, ctypes.c_int32, ctypes.POINTER(PKVector3)
    ]
    lib.Mesh_GetVertex.restype = None

    lib.Mesh_GetTriangleV.argtypes = [
        PKHANDLE, PKHANDLE, ctypes.c_int32,
        ctypes.POINTER(PKVector3),
        ctypes.POINTER(PKVector3),
        ctypes.POINTER(PKVector3),
    ]
    lib.Mesh_GetTriangleV.restype = None

    lib.Mesh_GetBoundingBox.argtypes = [
        PKHANDLE, PKHANDLE, ctypes.POINTER(PKBBox3)
    ]
    lib.Mesh_GetBoundingBox.restype = None

    lib.Mesh_bIsValid.argtypes = [PKHANDLE, PKHANDLE]
    lib.Mesh_bIsValid.restype = ctypes.c_bool

    lib.Mesh_Destroy.argtypes = [PKHANDLE, PKHANDLE]
    lib.Mesh_Destroy.restype = None

    # ---- Lattice (только базовая) ----
    lib.Lattice_hCreate.argtypes = [PKHANDLE]
    lib.Lattice_hCreate.restype = PKHANDLE

    lib.Lattice_AddSphere.argtypes = [
        PKHANDLE, PKHANDLE, ctypes.POINTER(PKVector3), ctypes.c_float
    ]
    lib.Lattice_AddSphere.restype = None

    lib.Lattice_Destroy.argtypes = [PKHANDLE, PKHANDLE]
    lib.Lattice_Destroy.restype = None

    # ---- Lattice (расширенно) ----
    lib.Lattice_AddBeam.argtypes = [
        PKHANDLE, PKHANDLE,
        ctypes.POINTER(PKVector3), ctypes.POINTER(PKVector3),
        ctypes.c_float, ctypes.c_float,
    ]
    lib.Lattice_AddBeam.restype = None

    # ---- Voxels (расширенно) ----
    lib.Voxels_RenderLattice.argtypes = [PKHANDLE, PKHANDLE, PKHANDLE]
    lib.Voxels_RenderLattice.restype = None

    lib.Voxels_RenderMesh.argtypes = [PKHANDLE, PKHANDLE, PKHANDLE]
    lib.Voxels_RenderMesh.restype = None

    lib.Voxels_hCreateMeshShell.argtypes = [PKHANDLE, PKHANDLE, ctypes.c_float]
    lib.Voxels_hCreateMeshShell.restype = PKHANDLE

    lib.Voxels_bIsInside.argtypes = [
        PKHANDLE, PKHANDLE, ctypes.POINTER(PKVector3)
    ]
    lib.Voxels_bIsInside.restype = ctypes.c_bool

    lib.Voxels_GetSurfaceNormal.argtypes = [
        PKHANDLE, PKHANDLE,
        ctypes.POINTER(PKVector3), ctypes.POINTER(PKVector3),
    ]
    lib.Voxels_GetSurfaceNormal.restype = None

    lib.Voxels_bRayCastToSurface.argtypes = [
        PKHANDLE, PKHANDLE,
        ctypes.POINTER(PKVector3), ctypes.POINTER(PKVector3),
        ctypes.POINTER(PKVector3), ctypes.POINTER(ctypes.c_float),
    ]
    lib.Voxels_bRayCastToSurface.restype = ctypes.c_bool

    # Правильная сигнатура: (hInstance, hThis, PKBBox3*, SDF_CB)
    SDF_CB_TYPE = ctypes.CFUNCTYPE(
        ctypes.c_float,
        ctypes.POINTER(PKVector3)
    )
    lib.Voxels_RenderImplicit.argtypes = [
        PKHANDLE,                    # hInstance
        PKHANDLE,                    # hThis (voxels)
        ctypes.POINTER(PKBBox3),     # poBBox
    ctypes.c_void_p,
]
    lib.Voxels_RenderImplicit.restype = None

    # IntersectImplicit — ещё мощнее: пересекает существующие воксели с SDF
    lib.Voxels_IntersectImplicit.argtypes = [
        PKHANDLE,                    # hInstance
        PKHANDLE,                    # hThis (voxels)
    ctypes.c_void_p,
]
    lib.Voxels_IntersectImplicit.restype = None


# ============================================================
# ВЫСОКОУРОВНЕВАЯ ОБЁРТКА
# ============================================================
class PicoGK:
    """Удобный интерфейс для PicoGK."""

    def __init__(self, voxel_size_mm: float = 0.5):
        """
        voxel_size_mm — размер вокселя в мм.
          Меньше = точнее, но медленнее и больше памяти.
          Типичные значения: 0.2 – 2.0 мм.
        """
        lib = _load_library()
        if lib is None:
            raise RuntimeError("PicoGK library not loaded")

        _init_prototypes(lib)
        self.lib = lib
        self.voxel_size_mm = voxel_size_mm
        self.instance = lib.Library_hCreateInstance(float(voxel_size_mm))

        if not self.instance:
            raise RuntimeError("Library_hCreateInstance вернул 0")

        # Отслеживание ресурсов для чистки
        self._voxels = []
        self._meshes = []
        self._lattices = []

        logger.info(f"PicoGK инстанс создан: voxel={voxel_size_mm} мм")

    # ---- Версия ----
    def version(self) -> str:
        buf = ctypes.create_string_buffer(255)
        self.lib.Library_GetVersion(buf)
        return buf.value.decode("utf-8", errors="ignore")

    # ============================================================
    # СОЗДАНИЕ ГЕОМЕТРИИ
    # ============================================================
    def sphere(self, center=(0.0, 0.0, 0.0), radius=10.0):
        """Создать сферу. Возвращает handle PKVOXELS."""
        c = PKVector3(*center)
        v = self.lib.Voxels_hCreateSphere(
            self.instance, ctypes.byref(c), float(radius)
        )
        if not v:
            raise RuntimeError("Voxels_hCreateSphere вернул 0")
        self._voxels.append(v)
        return v

    def capsule(self, start=(0, 0, 0), stop=(0, 0, 10), r1=5.0, r2=5.0):
        """Капсула (цилиндр с шаровыми торцами)."""
        p1 = PKVector3(*start)
        p2 = PKVector3(*stop)
        v = self.lib.Voxels_hCreateCapsule(
            self.instance,
            ctypes.byref(p1), ctypes.byref(p2),
            float(r1), float(r2),
        )
        if not v:
            raise RuntimeError("Voxels_hCreateCapsule вернул 0")
        self._voxels.append(v)
        return v

    def copy(self, voxels):
        """Копия воксельного объекта."""
        v = self.lib.Voxels_hCreateCopy(self.instance, voxels)
        self._voxels.append(v)
        return v

    # ============================================================
    # БУЛЕВЫ (не мутируют исходники, возвращают новый объект)
    # ============================================================
    def add(self, a, b):
        c = self.copy(a)
        self.lib.Voxels_BoolAdd(self.instance, c, b)
        return c

    def subtract(self, a, b):
        c = self.copy(a)
        self.lib.Voxels_BoolSubtract(self.instance, c, b)
        return c

    def intersect(self, a, b):
        c = self.copy(a)
        self.lib.Voxels_BoolIntersect(self.instance, c, b)
        return c

    # ============================================================
    # РЕШЁТКИ (LATTICE)
    # ============================================================
    def lattice_create(self):
        """Создать пустой объект-решётку."""
        l = self.lib.Lattice_hCreate(self.instance)
        self._lattices.append(l)
        return l

    def lattice_add_sphere(self, lattice, center=(0, 0, 0), radius=1.0):
        c = PKVector3(*center)
        self.lib.Lattice_AddSphere(self.instance, lattice, ctypes.byref(c), float(radius))

    def lattice_add_beam(self, lattice, p1=(0, 0, 0), p2=(0, 0, 10), r1=1.0, r2=1.0):
        a = PKVector3(*p1)
        b = PKVector3(*p2)
        self.lib.Lattice_AddBeam(
            self.instance, lattice,
            ctypes.byref(a), ctypes.byref(b),
            float(r1), float(r2),
        )

    def render_lattice(self, lattice):
        """Преобразовать латтис в воксели."""
        v = self.lib.Voxels_hCreate(self.instance, float(self.voxel_size_mm))
        self.lib.Voxels_RenderLattice(self.instance, v, lattice)
        self._voxels.append(v)
        return v

    # ============================================================
    # ИМПЛИЦИТ-ФУНКЦИИ (через RenderImplicit)
    # ============================================================
    def render_implicit(self, sdf_func, bbox_min, bbox_max):
        """
        Заполнить воксели по SDF-функции.
        sdf_func(x, y, z) -> float (расстояние со знаком, мм)

        Внутри PicoGK: bbox — прямоугольник для расчёта,
        sdf_func вызывается для каждой воксели в этом bbox.
        """
        SDF_CB = ctypes.CFUNCTYPE(
            ctypes.c_float,
            ctypes.POINTER(PKVector3)
        )

        def _cb(pvec):
            v = pvec.contents
            return float(sdf_func(v.x, v.y, v.z))

        cb = SDF_CB(_cb)
        # Защита от GC
        self._sdf_callbacks = getattr(self, "_sdf_callbacks", [])
        self._sdf_callbacks.append(cb)

        v = self.lib.Voxels_hCreate(self.instance, float(self.voxel_size_mm))
        self._voxels.append(v)

        bbox = PKBBox3()
        bbox.vecMin = PKVector3(float(bbox_min[0]), float(bbox_min[1]), float(bbox_min[2]))
        bbox.vecMax = PKVector3(float(bbox_max[0]), float(bbox_max[1]), float(bbox_max[2]))

        self.lib.Voxels_RenderImplicit(
            self.instance, v, ctypes.byref(bbox), cb,
        )
        return v

    def intersect_implicit(self, voxels, sdf_func):
        """
        Пересечь существующие воксели с SDF-функцией.
        Полезно для сложных форм: сначала box/sphere, потом вырезать SDF.
        """
        SDF_CB = ctypes.CFUNCTYPE(
            ctypes.c_float,
            ctypes.POINTER(PKVector3)
        )

        def _cb(pvec):
            v = pvec.contents
            return float(sdf_func(v.x, v.y, v.z))

        cb = SDF_CB(_cb)
        self._sdf_callbacks = getattr(self, "_sdf_callbacks", [])
        self._sdf_callbacks.append(cb)

        self.lib.Voxels_IntersectImplicit(self.instance, voxels, cb)
        return voxels

    # ============================================================
    # МЕШ-ОБОЛОЧКА
    # ============================================================
    def mesh_shell(self, mesh_handle, thickness):
        v = self.lib.Voxels_hCreateMeshShell(
            self.instance, mesh_handle, float(thickness)
        )
        self._voxels.append(v)
        return v

    # ============================================================
    # УТИЛИТЫ
    # ============================================================
    def is_inside(self, voxels, point):
        p = PKVector3(*point)
        return bool(self.lib.Voxels_bIsInside(self.instance, voxels, ctypes.byref(p)))

    def to_trimesh(self, voxels):
        """Конвертирует voxels в trimesh.Trimesh (для совместимости с UI)."""
        import trimesh
        import numpy as np
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
        tmp.close()
        try:
            self.save_stl(voxels, tmp.name)
            m = trimesh.load(tmp.name)
            return m
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def offset(self, voxels, distance):
        c = self.copy(voxels)
        self.lib.Voxels_Offset(self.instance, c, float(distance))
        return c

    # ============================================================
    # ИНФОРМАЦИЯ
    # ============================================================
    def volume(self, voxels) -> float:
        return float(self.lib.Voxels_fCalculateVolume(self.instance, voxels))

    def is_valid(self, voxels) -> bool:
        return bool(self.lib.Voxels_bIsValid(self.instance, voxels))

    # ============================================================
    # МЕШ
    # ============================================================
    def to_mesh(self, voxels):
        m = self.lib.Mesh_hCreateFromVoxels(self.instance, voxels)
        if not m:
            raise RuntimeError("Mesh_hCreateFromVoxels вернул 0")
        self._meshes.append(m)
        return m

    def triangle_count(self, mesh) -> int:
        return int(self.lib.Mesh_nTriangleCount(self.instance, mesh))

    def vertex_count(self, mesh) -> int:
        return int(self.lib.Mesh_nVertexCount(self.instance, mesh))

    def bounding_box(self, mesh) -> PKBBox3:
        bb = PKBBox3()
        self.lib.Mesh_GetBoundingBox(self.instance, mesh, ctypes.byref(bb))
        return bb

    # ============================================================
    # STL ЭКСПОРТ (на Python)
    # ============================================================
    def save_stl(self, voxels, path: str) -> str:
        """
        Сохранить voxels в бинарный STL.
        Итерируем треугольники через Mesh_GetTriangleV.
        """
        mesh = self.to_mesh(voxels)
        n = self.triangle_count(mesh)
        logger.info(f"[PicoGK] Экспорт STL: {n} треугольников → {path}")

        a = PKVector3()
        b = PKVector3()
        c = PKVector3()

        with open(path, "wb") as f:
            # 80-байтный заголовок
            header = b"Urfin Jus / PicoGK".ljust(80, b"\0")
            f.write(header)

            # Количество треугольников (uint32 little-endian)
            f.write(struct.pack("<I", n))

            for i in range(n):
                self.lib.Mesh_GetTriangleV(
                    self.instance, mesh, i,
                    ctypes.byref(a), ctypes.byref(b), ctypes.byref(c),
                )
                # Нормаль
                ux, uy, uz = b.x - a.x, b.y - a.y, b.z - a.z
                vx, vy, vz = c.x - a.x, c.y - a.y, c.z - a.z
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                ln = (nx * nx + ny * ny + nz * nz) ** 0.5
                if ln > 1e-12:
                    nx, ny, nz = nx / ln, ny / ln, nz / ln
                else:
                    nx = ny = nz = 0.0

                f.write(struct.pack(
                    "<12fH",
                    nx, ny, nz,
                    a.x, a.y, a.z,
                    b.x, b.y, b.z,
                    c.x, c.y, c.z,
                    0,
                ))

        return path

    # ============================================================
    # ЧИСТКА
    # ============================================================
    def cleanup(self):
        try:
            for m in self._meshes:
                try:
                    self.lib.Mesh_Destroy(self.instance, m)
                except Exception:
                    pass
            self._meshes.clear()

            for v in self._voxels:
                try:
                    self.lib.Voxels_Destroy(self.instance, v)
                except Exception:
                    pass
            self._voxels.clear()

            for l in self._lattices:
                try:
                    self.lib.Lattice_Destroy(self.instance, l)
                except Exception:
                    pass
            self._lattices.clear()

            if self.instance:
                try:
                    self.lib.Library_DestroyInstance(self.instance)
                except Exception:
                    pass
                self.instance = 0
        except Exception as e:
            logger.debug(f"cleanup: {e}")

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass


# ============================================================
# СИНГЛТОН
# ============================================================
_picogk_instance: Optional[PicoGK] = None


def get_picogk(voxel_size_mm: float = 0.5) -> PicoGK:
    """Возвращает singleton-инстанс PicoGK."""
    global _picogk_instance
    if _picogk_instance is None or _picogk_instance.instance == 0:
        _picogk_instance = PicoGK(voxel_size_mm)
    return _picogk_instance