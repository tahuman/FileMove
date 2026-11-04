#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileMove の GUI を exe（Windows 用、1 ファイル）にする。Python の無い PC でもダブルクリックで使える。

    python -m pip install -r requirements-dev.txt   # PyInstaller・sv-ttk・tkinterdnd2 など
    python tools/build_exe.py                       # -> dist/FileMove.exe（署名と自己診断も行う）
    python tools/build_exe.py --no-sign --no-test   # 署名・自己診断を省く

見た目（sv-ttk）とドラッグ＆ドロップ（tkinterdnd2）も exe に入れる。作業用のファイルは build/ に置く。

署名: 自分で作った証明書（自己署名、いわゆるオレオレ証明書）で exe に署名する。証明書は初回に
Windows の「個人」の証明書ストア（Cert:\\CurrentUser\\My）に「CN=FileMove (self-signed)」として作り、
以後は同じものを使う（秘密鍵はこの PC から出さない）。公開鍵の証明書は dist/FileMove.cer に書き出す。
自己署名なので、ほかの PC では「発行元を確認できません」の扱いのまま（警告を消すには正規の証明書が要る）。
この PC で「信頼できる発行元」として扱いたいときは、dist/FileMove.cer をダブルクリックして
「信頼されたルート証明機関」に入れる（自分の判断で行う。このスクリプトは信頼の設定まではしない）。

自己診断: 作った後に `FileMove.exe --self-test` を実行し、画面を出さずに「確認 → 実行」まで動くかを確かめる。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # migrate_files（バージョン）
DIST, BUILD = ROOT / "dist", ROOT / "build"
EXE = DIST / "FileMove.exe"
CERT_SUBJECT = "CN=FileMove (self-signed)"


def write_version_file(path: Path) -> Path:
    """exe のファイルのプロパティ（詳細タブ）に出すバージョン情報を、PyInstaller の形式で書く。"""
    from migrate_files import __version__
    nums = tuple(int(n) for n in __version__.split(".")) + (0,)
    file_version = ".".join(map(str, nums))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[
    StringFileInfo([StringTable('041104B0', [
      StringStruct('ProductName', 'FileMove'),
      StringStruct('FileDescription', 'FileMove（フォルダの構成を保ったままファイルを移動・コピー）'),
      StringStruct('ProductVersion', '{__version__}'),
      StringStruct('FileVersion', '{file_version}'),
      StringStruct('OriginalFilename', 'FileMove.exe'),
      StringStruct('LegalCopyright', 'tahuman')])]),
    VarFileInfo([VarStruct('Translation', [0x0411, 1200])])
  ]
)
""", encoding="utf-8")
    return path


def build() -> None:
    import PyInstaller.__main__
    version_file = write_version_file(BUILD / "version_info.txt")
    PyInstaller.__main__.run([
        str(ROOT / "gui" / "FileMove.pyw"),
        "--name", "FileMove",
        "--onefile", "--windowed", "--noconfirm", "--clean",
        "--paths", str(ROOT),                      # migrate_files と gui
        "--collect-data", "sv_ttk",                # 見た目（テーマの画像と tcl）
        "--collect-all", "tkinterdnd2",            # ドラッグ＆ドロップ（tkdnd の DLL）
        "--version-file", str(version_file),       # ファイルのプロパティのバージョン
        "--distpath", str(DIST), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
    ])


def _powershell(script: str) -> str:
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def sign(exe: Path = EXE) -> str:
    """自己署名の証明書（無ければ作る）で exe に署名し、署名した証明書の拇印を返す。"""
    cer = exe.with_suffix(".cer")
    script = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$cert = Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert |
    Where-Object {{ $_.Subject -eq '{CERT_SUBJECT}' -and $_.NotAfter -gt (Get-Date).AddDays(30) }} |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) {{
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject '{CERT_SUBJECT}' `
        -CertStoreLocation Cert:\\CurrentUser\\My -NotAfter (Get-Date).AddYears(5) -KeyExportPolicy NonExportable
}}
# 自己署名なので Status は「信頼されていないルート」になるが、署名そのものは付く（下で拇印を確かめる）
Set-AuthenticodeSignature -FilePath '{exe}' -Certificate $cert -HashAlgorithm SHA256 | Out-Null
Export-Certificate -Cert $cert -FilePath '{cer}' -Force | Out-Null
$signed = (Get-AuthenticodeSignature -FilePath '{exe}').SignerCertificate
if (-not $signed -or $signed.Thumbprint -ne $cert.Thumbprint) {{ throw '署名を確かめられません' }}
$cert.Thumbprint
"""
    return _powershell(script)


def self_test(exe: Path = EXE) -> bool:
    """exe を --self-test で起動し、結果を表示する。"""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "self_test.txt"
        proc = subprocess.run([str(exe), "--self-test", str(report)], timeout=300)
        text = report.read_text(encoding="utf-8") if report.exists() else "（結果のファイルがありません）\n"
    print(text, end="")
    return proc.returncode == 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FileMove の GUI を exe にする")
    ap.add_argument("--no-sign", action="store_true", help="署名を省く")
    ap.add_argument("--no-test", action="store_true", help="作った後の自己診断を省く")
    args = ap.parse_args(argv)
    if sys.platform != "win32":
        print("exe 化は Windows で行ってください", file=sys.stderr)
        return 2
    build()
    print(f"作成: {EXE.relative_to(ROOT)}（{EXE.stat().st_size // (1024 * 1024)}MB）")
    if not args.no_sign:
        print(f"署名: {CERT_SUBJECT}（拇印 {sign()}）。証明書: {EXE.with_suffix('.cer').relative_to(ROOT)}")
    if args.no_test:
        return 0
    ok = self_test()
    print("自己診断: " + ("正常" if ok else "異常"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
