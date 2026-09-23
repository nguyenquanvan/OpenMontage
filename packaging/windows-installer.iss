#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppBuild
  #define AppBuild "local"
#endif
#ifndef SourceDir
  #define SourceDir AddBackslash(SourcePath) + "..\dist\MOSA TOOL ALL"
#endif
#ifndef OutputDir
  #define OutputDir AddBackslash(SourcePath) + "..\dist"
#endif

[Setup]
AppId={{8C5A1BA4-2AF4-4C46-8C0C-BFDAB2954064}
AppName=MOSA TOOL ALL
AppVersion={#AppVersion}
AppVerName=MOSA TOOL ALL {#AppVersion}
AppPublisher=MOSA TOOL ALL
AppPublisherURL=https://github.com/nguyenquanvan/OpenMontage
AppSupportURL=https://github.com/nguyenquanvan/OpenMontage/issues
AppUpdatesURL=https://github.com/nguyenquanvan/OpenMontage/releases
DefaultDirName={localappdata}\Programs\MOSA TOOL ALL
DefaultGroupName=MOSA TOOL ALL
DisableProgramGroupPage=yes
LicenseFile={#SourcePath}\..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=MOSA-TOOL-ALL-Setup-{#AppVersion}-{#AppBuild}-win-x64
SetupIconFile={#SourcePath}\..\build\mosa-tool-all.ico
UninstallDisplayIcon={app}\MOSA TOOL ALL.exe
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName=MOSA TOOL ALL
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany=MOSA TOOL ALL
VersionInfoDescription=MOSA TOOL ALL Windows Installer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài màn hình"; GroupDescription: "Biểu tượng bổ sung:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MOSA TOOL ALL"; Filename: "{app}\MOSA TOOL ALL.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\MOSA TOOL ALL"; Filename: "{app}\MOSA TOOL ALL.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\MOSA TOOL ALL.exe"; Description: "Mở MOSA TOOL ALL"; Flags: nowait postinstall skipifsilent
