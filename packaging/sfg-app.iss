; Inno Setup script for SFG-App.
;
; Build with (after `uv run pyinstaller packaging/sfg-app.spec` has
; already produced dist/SFG-App/):
;   iscc /DMyAppVersion=1.0.0 packaging\sfg-app.iss
; Output in: packaging/installer_output/SFG-App-Setup-<version>.exe
;
; Requires Inno Setup 6 (https://jrsoftware.org/isinfo.php), or
; `choco install innosetup` in CI -- see .github/workflows/release.yml,
; which builds this automatically for every pushed version tag.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
; Fixed GUID -- keep this the same across every future version so
; installing a new one upgrades in place instead of side-by-side.
AppId={{A7F3D8C2-4B91-4E6A-9C3D-2F8B6A1E5D74}
AppName=SFG-App
AppVersion={#MyAppVersion}
AppPublisher=Simon Langlois
AppPublisherURL=https://github.com/silanglois/SFG-App
DefaultDirName={autopf}\SFG-App
DefaultGroupName=SFG-App
UninstallDisplayIcon={app}\SFG-App.exe
OutputDir=installer_output
OutputBaseFilename=SFG-App-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
SetupIconFile=icon.ico
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\SFG-App\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SFG-App"; Filename: "{app}\SFG-App.exe"
Name: "{group}\Uninstall SFG-App"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SFG-App"; Filename: "{app}\SFG-App.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SFG-App.exe"; Description: "Launch SFG-App"; Flags: nowait postinstall skipifsilent
