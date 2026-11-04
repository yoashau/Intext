"""Antialiased freehand fills, shared by the live selection and final crop."""

from __future__ import annotations

import ctypes
from array import array
from ctypes import wintypes
from itertools import chain

from .screenshot import freehand_path


class _Startup(ctypes.Structure):
    _fields_ = (("version", wintypes.UINT), ("callback", ctypes.c_void_p),
                ("no_thread", wintypes.BOOL), ("no_codecs", wintypes.BOOL))


class FreehandFill:
    """Fill a smooth path with frozen screenshot pixels, without any stroke."""

    def __init__(self, source):
        self.source = source
        self.api = ctypes.WinDLL("gdiplus", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        pointer, integer = ctypes.c_void_p, ctypes.c_int
        output = ctypes.POINTER(pointer)
        signatures = {
            "GdiplusStartup": [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(_Startup), pointer],
            "GdiplusShutdown": [ctypes.c_size_t],
            "GdipCreateBitmapFromScan0": [integer, integer, integer, integer, pointer, output],
            "GdipDisposeImage": [pointer],
            "GdipCreateTexture": [pointer, integer, output],
            "GdipDeleteBrush": [pointer],
            "GdipCreateFromHDC": [wintypes.HDC, output],
            "GdipDeleteGraphics": [pointer],
            "GdipSetSmoothingMode": [pointer, integer],
            "GdipSetPixelOffsetMode": [pointer, integer],
            "GdipSetInterpolationMode": [pointer, integer],
            "GdipSetClipRectI": [pointer, integer, integer, integer, integer, integer],
            "GdipCreatePath2": [pointer, pointer, integer, integer, output],
            "GdipDeletePath": [pointer],
            "GdipFillPath": [pointer, pointer, pointer],
            "GdipClonePath": [pointer, output],
            "GdipCreatePen1": [wintypes.DWORD, ctypes.c_float, integer, output],
            "GdipDeletePen": [pointer],
            "GdipWidenPath": [pointer, pointer, pointer, ctypes.c_float],
            "GdipSetPathFillMode": [pointer, integer],
            "GdipCreateRegionPath": [pointer, output],
            "GdipDeleteRegion": [pointer],
            "GdipGetRegionHRgn": [pointer, pointer, output],
            "GdipSetClipHrgn": [pointer, pointer, integer],
        }
        for name, args in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, integer
        self.api.GdiplusShutdown.restype = None
        for name, args in {
            "GdiFlush": [], "SaveDC": [pointer], "RestoreDC": [pointer, integer],
            "CombineRgn": [pointer, pointer, pointer, integer],
            "ExtSelectClipRgn": [pointer, pointer, integer], "DeleteObject": [pointer],
            "BitBlt": [pointer, integer, integer, integer, integer, pointer, integer, integer, wintypes.DWORD],
        }.items():
            function = getattr(self.gdi, name)
            function.argtypes, function.restype = args, integer
        self.token = ctypes.c_size_t()
        self.bitmap, self.brush, self.band_pen = pointer(), pointer(), pointer()
        try:
            self.check(self.api.GdiplusStartup(ctypes.byref(self.token), ctypes.byref(_Startup(1)), None))
            # RGB ignores the screenshot DIB's unused alpha byte.
            self.check(self.api.GdipCreateBitmapFromScan0(source.width, source.height, source.width*4,
                       0x22009, source.bits, ctypes.byref(self.bitmap)))  # PixelFormat32bppRGB
            self.check(self.api.GdipCreateTexture(self.bitmap, 4, ctypes.byref(self.brush)))  # WrapModeClamp
            # This pen only defines a narrow work region. It is never drawn.
            self.check(self.api.GdipCreatePen1(0xFFFFFFFF, 6.0, 2, ctypes.byref(self.band_pen)))
        except Exception:
            self.close()
            raise

    @staticmethod
    def check(status):
        if status:
            raise OSError(f"Freehand selection rendering failed ({status})")

    def draw(self, dc, points, clip):
        path_points, kinds = freehand_path(points)
        if not path_points:
            return
        coordinates = array("f", chain.from_iterable(path_points))
        vertices = (ctypes.c_float * len(coordinates)).from_buffer(coordinates)
        types = (ctypes.c_ubyte * len(kinds)).from_buffer_copy(kinds)
        path, graphics, edge_path = (ctypes.c_void_p() for _ in range(3))
        interior, edge = ctypes.c_void_p(), ctypes.c_void_p()
        interior_rgn, edge_rgn = ctypes.c_void_p(), ctypes.c_void_p()
        try:
            self.check(self.api.GdipCreatePath2(vertices, types, len(kinds), 0, ctypes.byref(path)))  # Alternate fill
            self.check(self.api.GdipCreateFromHDC(dc, ctypes.byref(graphics)))
            self.check(self.api.GdipClonePath(path, ctypes.byref(edge_path)))
            self.check(self.api.GdipWidenPath(edge_path, self.band_pen, None, .25))
            self.check(self.api.GdipSetPathFillMode(edge_path, 1))  # Winding
            self.check(self.api.GdipCreateRegionPath(path, ctypes.byref(interior)))
            self.check(self.api.GdipCreateRegionPath(edge_path, ctypes.byref(edge)))
            self.check(self.api.GdipGetRegionHRgn(interior, graphics, ctypes.byref(interior_rgn)))
            self.check(self.api.GdipGetRegionHRgn(edge, graphics, ctypes.byref(edge_rgn)))
            self.api.GdipDeleteGraphics(graphics)
            graphics.value = None
            # Leave the edge band on its original background so antialiasing
            # composites exactly once. The opaque interior needs only BitBlt.
            if not self.gdi.CombineRgn(interior_rgn, interior_rgn, edge_rgn, 4):  # RGN_DIFF
                raise ctypes.WinError(ctypes.get_last_error())
            saved = self.gdi.SaveDC(dc)
            if not saved:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not self.gdi.ExtSelectClipRgn(dc, interior_rgn, 1):  # RGN_AND
                    raise ctypes.WinError(ctypes.get_last_error())
                if not self.gdi.BitBlt(dc, *clip, self.source.dc, clip[0], clip[1], 0x00CC0020):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self.gdi.RestoreDC(dc, saved)
            self.gdi.GdiFlush()
            self.check(self.api.GdipCreateFromHDC(dc, ctypes.byref(graphics)))
            self.check(self.api.GdipSetSmoothingMode(graphics, 5))  # AntiAlias8x8, equal quality on both axes
            self.check(self.api.GdipSetPixelOffsetMode(graphics, 4))  # Half
            self.check(self.api.GdipSetInterpolationMode(graphics, 5))  # NearestNeighbor
            self.check(self.api.GdipSetClipHrgn(graphics, edge_rgn, 0))
            self.check(self.api.GdipSetClipRectI(graphics, *clip, 1))  # Intersect
            self.check(self.api.GdipFillPath(graphics, self.brush, path))
        finally:
            for region in (interior_rgn, edge_rgn):
                if region:
                    self.gdi.DeleteObject(region)
            for region in (interior, edge):
                if region:
                    self.api.GdipDeleteRegion(region)
            if edge_path:
                self.api.GdipDeletePath(edge_path)
            if graphics:
                self.api.GdipDeleteGraphics(graphics)
            if path:
                self.api.GdipDeletePath(path)

    def close(self):
        if self.band_pen:
            self.api.GdipDeletePen(self.band_pen)
            self.band_pen = None
        if self.brush:
            self.api.GdipDeleteBrush(self.brush)
            self.brush = None
        if self.bitmap:
            self.api.GdipDisposeImage(self.bitmap)
            self.bitmap = None
        if self.token.value:
            self.api.GdiplusShutdown(self.token)
            self.token.value = 0
