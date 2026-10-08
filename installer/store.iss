; Inno Setup script of Al-Store (built by tools/build_windows.py).
; The same Al-Store-Setup.exe installs the program on a new PC and updates it on a PC that already has it:
; only the program in Program Files is replaced, the shop's data in %ProgramData%\Al-Store is never touched.

#define MyAppName "Al-Store"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppPublisher
  #define AppPublisher "Apps Factory"
#endif

[Setup]
AppId={{6F1D5B7A-3C42-4E0B-9A57-2B8C5D1E7F60}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\Al-Store
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
DisableDirPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Al-Store-Setup-{#AppVersion}
SetupIconFile=..\build\store.ico
UninstallDisplayIcon={app}\Al-Store.exe
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
arabic.DesktopIcon=ضع أيقونة على سطح المكتب
english.DesktopIcon=Put an icon on the desktop
arabic.AutoStart=التشغيل مع ويندوز (موصى به: البرنامج يكون جاهز أول ما تفتح الجهاز)
english.AutoStart=Start with Windows (recommended - the program is ready as soon as the PC is on)
arabic.Firewall=السماح لموبايلات المحل على نفس الواي فاي بالدخول...
english.Firewall=Allowing the shop's phones on the same Wi-Fi to connect...
arabic.OpenNow=افتح «الستور» الآن
english.OpenNow=Open Al-Store now
arabic.Practice=الستور - وضع التدريب
english.Practice=Al-Store - practice shop

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"
Name: "autostart"; Description: "{cm:AutoStart}"

[Dirs]
; data, backups and settings: writable for everybody who uses this PC, kept when the program is updated or removed
Name: "{commonappdata}\Al-Store"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\Al-Store-practice"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "..\build\app.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\Al-Store.exe"
Name: "{autoprograms}\{cm:Practice}"; Filename: "{app}\Al-Store.exe"; Parameters: "--practice"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\Al-Store.exe"; Tasks: desktopicon
Name: "{commonstartup}\{#MyAppName}"; Filename: "{app}\Al-Store.exe"; Parameters: "--no-browser"; Tasks: autostart

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#MyAppName}"""; Flags: runhidden; StatusMsg: "{cm:Firewall}"
; only the shop's own (private or domain) network: a PC on a café or public Wi-Fi never lets strangers in
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#MyAppName}"" dir=in action=allow program=""{app}\Al-Store.exe"" enable=yes profile=private,domain"; Flags: runhidden
Filename: "{app}\Al-Store.exe"; Description: "{cm:OpenNow}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Al-Store.exe"; Flags: runhidden; RunOnceId: "StopStore"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#MyAppName}"""; Flags: runhidden; RunOnceId: "FirewallRule"

[Messages]
arabic.FinishedLabel=تم تثبيت البرنامج. بيانات المحل محفوظة في %ProgramData%\Al-Store وبتفضل موجودة بعد التحديثات.%n%nلو الموبايلات مش بتتصل: خلّي شبكة المحل «خاصة» (Private) من إعدادات ويندوز. الشبكات العامة مش بتتسمح حفاظًا على بياناتك.
english.FinishedLabel=The program is installed. The shop's data is kept in %ProgramData%\Al-Store (also after updates).%n%nIf phones cannot connect: set the shop's network to Private in Windows Settings. Public networks are never allowed in, to protect the data.

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  { stop the running program (it is safe to stop at any moment), so its files can be replaced }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Al-Store.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(1000);
  Result := '';
end;
