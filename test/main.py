#!/usr/bin/env python

####################################
#                                  #
# Import all modules: configure... #
#                                  #
####################################
import xde_world_manager as xwm


TIME_STEP = .01

wm = xwm.WorldManager()

wm.createAllAgents(TIME_STEP)

wm.startAgents()

import xdefw.interactive
xdefw.interactive.shell_console()()



