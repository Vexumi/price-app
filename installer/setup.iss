; Inno Setup: собирает setup.exe из готовой PyInstaller-сборки
; (..\dist\PriceApp\, см. price_app.spec). Компилируется на windows-latest
; в GitHub Actions (см. .github/workflows/build-windows.yml).
;
; AppId - случайный фиксированный GUID: не менять между версиями, иначе
; Windows будет считать каждую сборку новой программой вместо обновления.
#define MyAppName "Ценовой срез"
#define MyAppVersion "0.1.0"
#define MyAppExeName "PriceApp.exe"

[Setup]
AppId={{8A4E80EB-488F-4AE1-AB7C-B320EE8CEC52}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\installer_output
OutputBaseFilename=setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
; Не подписан сертификатом - на чистой машине Windows SmartScreen покажет
; предупреждение "Windows защитила ваш компьютер". Это ожидаемо для
; неподписанного установщика одного пользователя, не ошибка сборки.

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\PriceApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
