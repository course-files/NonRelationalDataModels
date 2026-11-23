#!/bin/bash
# Healthy only when THIS node shows as "UN" (Up, Normal) in nodetool status.
ip="$(hostname -i | awk '{print $1}')"
nodetool status 2>/dev/null | grep -E "^UN +${ip} " >/dev/null
