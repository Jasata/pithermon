#!/bin/bash
# 2018.08.28 // Jani Tammi
# Raspberry Pi stress/temperature test script
# Requires sysbench (apt-get install sysbench)


# init()
clear
declare -a cpu_active_prev
declare -a cpu_total_prev
read cpu user nice system idle iowait irq softirq steal guest< /proc/stat
cpu_active_prev=$((user+system+nice+softirq+steal))
cpu_total_prev=$((user+system+nice+softirq+steal+idle+iowait))

show_temps()
{
    now="$(date +'%T')"

    # CPU utilization
    read cpu user nice system idle iowait irq softirq steal guest< /proc/stat
    cpu_active_cur=$((user+system+nice+softirq+steal))
    cpu_total_cur=$((user+system+nice+softirq+steal+idle+iowait))
    cpu_util=$((100*( cpu_active_cur-cpu_active_prev ) / (cpu_total_cur-cpu_total_prev) ))
    # current become previous values
    cpu_active_prev = cpu_active_cur
    cpu_total_prev  = cpu_total_cur

    cpuTemp0=$(cat /sys/class/thermal/thermal_zone0/temp)
    cpuTemp1=$(($cpuTemp0/1000))
    cpuTemp2=$(($cpuTemp0/100))
    cpuTempM=$(($cpuTemp2 % $cpuTemp1))

    gpuTemp0=$(/opt/vc/bin/vcgencmd measure_temp)
    gpuTemp0=${gpuTemp0//\'/º}
    gpuTemp0=${gpuTemp0//temp=/}

    armFreq=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)
    armFreq=$(($armFreq/1000))

    echo [$now] $cpu_util CPU: $cpuTemp1"."$cpuTempM"ºC" GPU: $gpuTemp0 ARM: $armFreq" MHz"
}

for i in {1..10}
do
    show_temps
    sysbench --test=cpu --cpu-max-prime=20000 --num-threads=4 run >/dev/null 2>&1
done

show_temps

# EOF