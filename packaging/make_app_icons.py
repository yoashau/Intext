"""Reuse the current tray artwork and palette on all application surfaces."""
from shutil import copyfile
from make_icons import ASSET_DIR, SOURCE, TRAY_VARIANTS, build as build_tray_icons, render, write_png


def build() -> None:
    build_tray_icons()
    for name, color, opacity in TRAY_VARIANTS:
        dark = name == "tray-on-dark.ico"
        app_name = "intext-on-dark.ico" if dark else "intext.ico"
        # Byte-identical ICOs preserve every current tray frame, its padding,
        # edge coverage, and foreground opacity without a second rendering.
        copyfile(ASSET_DIR / name, ASSET_DIR / app_name)
        png_name = "mark-light.png" if dark else "mark.png"
        write_png(ASSET_DIR / png_name, 128, 128, render(128, color, SOURCE, opacity=opacity))
        print(f"wrote {app_name} and {png_name}: current tray artwork and palette")


if __name__ == "__main__":
    build()
