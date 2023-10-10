@ECHO OFF

set app_title=habitat-connectivity-tool
set root_dir=%~dp0..
set deploy_dir=%root_dir%\deploy
set out_file=%root_dir%\%app_title%_%DATE%.zip

del %root_dir%\%app_title%_*.zip
7z a %out_file% -tzip -r %deploy_dir%/*.*

pause