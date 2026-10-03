#!/bin/sh
# Run from SD on the parked unit. Output to the workstation or SD, NOT system/app.
# Lists and diagnostics only: no remount, kill, reboot, device writes or patch load.
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
export PATH
echo 'MU1320 read-only collection; store output privately'
echo '== OS =='
uname -a
echo '== Mounts =='
mount
echo '== Processes =='
pidin ar
echo '== Path resolution and metadata =='
ls -ld /etc /etc/eso /etc/eso/production /armle /armle/usr/lib/cinemo /mnt/app/armle/usr/lib/cinemo
ls -l /etc/eso/production/dio_manager.json /mnt/system/etc/eso/production/dio_manager.json
ls -l /etc/eso/production/smartphone_integrator.json /mnt/system/etc/eso/production/smartphone_integrator.json
ls -l /etc/scripts/carplay_cleanup.sh /mnt/app/eso/hmi/lsd/lsd.sh
ls -l /mnt/app/eso/hmi/lsd/jars /mnt/app/eso/hmi/lsd/hmi.zip /mnt/app/eso/hmi/lsd/lsd.jxe
ls -l /mnt/app/eso/hmi/lsd/development_activated
echo '== Cinemo plugin directory (configured by iap2.cinemoLib) =='
ls -la /armle/usr/lib/cinemo
ls -la /mnt/app/armle/usr/lib/cinemo
echo '== Configuration identity (cksum is NOT SHA-256) =='
cksum /etc/eso/production/dio_manager.json /mnt/system/etc/eso/production/dio_manager.json
cksum /etc/eso/production/smartphone_integrator.json /mnt/system/etc/eso/production/smartphone_integrator.json
echo '== Recovery prerequisites: only test existence; no permission changes =='
for tool in sh cp mv cmp cksum sync sleep chmod chown; do
    command -v "$tool"
done
echo '== End: missing optional paths above are diagnostic, not permission to create them =='
