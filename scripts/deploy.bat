REM @ECHO OFF

set app_title=hnat
set root_dir=%~dp0..
set deploy_dir=%root_dir%\deploy

rmdir %deploy_dir% /s /q
mkdir %deploy_dir%
mkdir %deploy_dir%\%app_title%

xcopy %root_dir%\src\%app_title%\*.py         %deploy_dir%\%app_title% /sy
xcopy %root_dir%\src\%app_title%\metadata.txt %deploy_dir%\%app_title% /y
copy  %root_dir%\doc\readme.txt               %deploy_dir%\%app_title% /y

pause