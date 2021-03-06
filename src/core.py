#!/xde

import contact
import markerManager
import collision

import desc
import desc.scene

import sys
import xdefw
import deploy.deployer as ddeployer

import xdefw.rtt


import agents.graphic.simple
import agents.graphic.proto
import agents.graphic.builder
import agents.physic.core
import agents.physic.builder

verbose = False

def verbose_print(msg):
    if verbose is True:
        print(msg)

class WorldManager():
    """ Middle layer to manage the different XDE agents.

    It always creates a clock agent (clock) and a physic agent (phy).
    This gives access to the main physical scene (ms), the geometrical scene (xcd)
    and a sync connector (icsync) to synchronize physic with asynchronous events.

    Besides, one can create a graphic agent (graph) which gives access to the
    graphical scene (graph_scn).
    """

    def __init__(self, corba=False):
        """ Initialize WorldManager instance.

        :param bool corba: If corba is set to True, it allows to make a proxy of a
                    distant physic agent. See methods:

                    * :meth:`getPhysicAgentFromCorba`
                    * :meth:`getGraphicAgentFromCorba`

        This world manager gives access to the following agents/scene (when created, None by default):

        * phy: the physical agent
        * graph: the graphical agent
        * clock: the clock agent, to get current time & periodically call physic
        * ms: the main physical scene, to get segment, joint, etc...
        * xcd: the geometrical scene, to get collision information, composite, etc...
        * graph_scn: the main graphical scene, to interacte with the displayed elements
        * icsync: the physic IConnectorSynchro, to make synchronization with the 'addEvent' method
        """
        self.phy       = None
        self.graph     = None
        self.clock     = None
        self.ms        = None
        self.xcd       = None
        self.graph_scn = None
        self.icsync    = None

        self._internal_z = 1

        self.contact = contact.Contact(self)
        self.collision = collision.Collision(self)

        self.corba = corba
        if corba:
            import rtt_interface_corba
            rtt_interface_corba.Init(sys.argv)


    def createClockAgent(self, time_step, clock_name="clock"):
        """ Create clock agent.

        :param double time_step: the tick period (in s)
        :param string clock_name: the name of the clock agent

        It initializes the following attribute in this world manager:
        * clock
        """
        verbose_print("CREATE CLOCK...")
        self.clock = xdefw.rtt.Task(ddeployer.load(clock_name, "dio::Clock", "dio-cpn-clock", ""))
        self.clock.s.setPeriod(time_step)

    def createPhysicAgent(self, time_step, dt, phy_name, lmd_max=0.01, uc_relaxation_factor=0.1):
        """ Create physical agent.

        :param double time_step: the period between two physic updates
        :param double dt: the physic integration time, can be different of the update call period
        :param string phy_name: the name of the physical agent
        :param double lmd_max: (local minimal distance) the threshold when the lmd is considered (beyond, global distance are considered)
        :param double uc_relaxation_factor: TODO!! if I remember well, it is related to the force distribution when two planes are in contact

        It initializes the following attributes in this world manager:
        * phy
        * ms
        * xcd
        * icsync
        """
        verbose_print("CREATE PHYSIC...")
        self.phy = agents.physic.core.createAgent(phy_name, 0)
        self.phy.s.setPeriod(time_step)

        #Init physic
        if dt is None:
            dt = time_step
        self.ms = agents.physic.core.createGVMScene(self.phy, "main", time_step=dt, uc_relaxation_factor=uc_relaxation_factor)
        self.xcd = agents.physic.core.createXCDScene(self.phy, "xcd", "LMD", lmd_max=lmd_max)
        self.ms.setGeometricalScene(self.xcd)

        self.phy.s.Connectors.OConnectorBodyStateList.new("ocb", "body_state")
        self.phy.s.Connectors.OConnectorContactBody.new("occ", "contacts")

        verbose_print("CREATE PORTS...")
        self.phy.addCreateInputPort("clock_trigger", "double")
        self.icsync = self.phy.s.Connectors.IConnectorSynchro.new("icsync")
        self.icsync.addEvent("clock_trigger")

    def createGraphicAgent(self, graph_name):
        """ Create graphical agent.

        :param string graph_name: the name of the graphical agent

        By default, the translucent ground is not shown. Call :meth:`graph_scn.SceneryInterface.showGround` to show it.
        """
        verbose_print("CREATE GRAPHIC...")
        self.graph = agents.graphic.simple.createAgent(graph_name, 0)

        #Init graphic
        self.graph_scn, scene_name, window_name, viewport_name = agents.graphic.simple.setupSingleGLView(self.graph)

        agents.graphic.proto.configureBasicLights(self.graph_scn)
        agents.graphic.proto.configureBasicCamera(self.graph_scn)
        self.graph.s.Viewer.enableNavigation(True)
        self.graph_scn.SceneryInterface.showGround(False)

        self.graph.s.Connectors.IConnectorBody.new("icb", "body_state_H", scene_name)    #to show bodies
        self.graph.s.Connectors.IConnectorFrame.new("icf", "framePosition", scene_name)  #to link with frames/markers
        self.graph.s.Connectors.IConnectorContacts.new("icc", "contacts", scene_name)    #to show contacts info

        self.graph.s.start()

        self.markers = markerManager.MarkerManager("MarkerManager", self.clock.s.getPeriod(), self)
        self.graph.getPort("framePosition").connectTo(self.markers.getPort("markerPositionPort_out"))
        self.markers.s.start()

    def connectGraphToPhysic(self):
        """ Connect graphical & physical agents, to show/update bodies/markers/contacts. """
        assert(self.graph is not None)
        assert(self.phy is not None)
        self.graph.getPort("body_state_H").connectTo(self.phy.getPort("body_state_H"))
        self.graph.getPort("contacts").connectTo(self.phy.getPort("contacts"))

    def disconnectGraphFromPhysic(self):
        """ Disconnect graphical & physical agents. """
        assert(self.graph is not None)
        assert(self.phy is not None)

        self.graph.getPort("body_state_H").disconnect()
        self.graph.getPort("framePosition").disconnect()
        self.graph.getPort("contacts").disconnect()

    # TODO: this method is deprecated, problem to connect physic & graphic agent
    #       we don't know how to load graph data with corba, if world has been created elsewhere
    def changePhy(self, phy_name):
        """ Problem and deprecated, no doc done. """
        self.disconnectGraphFromPhysic()
        self.cleanGraph()
        self.getPhysicAgentFromCorba(phy_name)
        if phy_name in self.phy_worlds: #TODO: problem here, because no more self.phy_worlds
            for world in self.phy_worlds[phy_name]:
                self.addWorldToGraphic(world)
        self.connectGraphToPhysic()

    def connectClockToPhysic(self):
        """ Connect clock to physic, to trigger phy update with the clock tick """
        assert(self.clock is not None)
        assert(self.phy is not None)
        self.clock.getPort("ticks").connectTo(self.phy.getPort("clock_trigger"))

    def startAgents(self):
        """ Start clock & physical agents.

        Note: the graphical agent, if created, is started when created.
        """
        if (self.clock is not None):
            self.clock.s.start()
        if (self.phy is not None):
            self.phy.s.start()


    def stopAgents(self):
        """ Stop clock & physical agents.
        """
        if (self.clock is not None):
            self.clock.s.stop()
        if (self.phy is not None):
            self.phy.s.stop()


    def createAllAgents(self, time_step, dt=None, phy_name="physic", lmd_max=0.01, uc_relaxation_factor=0.1, create_graphic=True, graph_name = "graphic"):
        """ Create all agents: clock, physic & graphic (if requested).

        :param double time_step: the period of time between two call of update for clock (Warning: phy is synchronized with clock, the update is called by clock tick, not period)
        :param double dt: the integration time for physic at each update call
        :param string phy_name: the name of the physical agent
        :param double lmd_max: (local minimal distance) the threshold when the lmd is considered (beyond, global distance are considered)
        :param double uc_relaxation_factor: TODO!! if I remember well, it is related to the force distribution when two planes are in contact
        :param bool create_graphic: if False, no physical agent is created; then, 'graph' & 'graph_scn' remain None
        :param string graph_name: the name of the graphical agent
        """
        self.createClockAgent(time_step)
        self.createPhysicAgent(time_step, dt, phy_name, lmd_max, uc_relaxation_factor)

        self.connectClockToPhysic()

        if create_graphic is True:
            self.createAndConnectGraphicAgent(graph_name)

    def createAndConnectGraphicAgent(self, graph_name):
        """ Create graphical agent & connect it with the physical agent. """
        self.createGraphicAgent(graph_name)
        self.connectGraphToPhysic()


    def getPhysicAgentFromCorba(self, phy_name):
        """ If corba has been set to True, proxy a remote physical agent.

        It also recovers ms (main scene) and xcd (geometrical scene).

        :param string phy_name: the remote physical agent name
        """
        if self.corba:
            import rtt_interface_corba
            phy_p = rtt_interface_corba.GetProxy(phy_name, False)
            self.phy = xdefw.rtt.Task(phy_p, binding_class = xdefw.rtt.ObjectStringBinding, static_classes=['agent'])

            self.ms = self.phy.s.GVM.Scene("main")
            self.xcd = self.phy.s.XCD.Scene("xcd")
        else:
            raise ImportError, "corba has not been selected"


    def getGraphicAgentFromCorba(self, graph_name):
        """ If corba has been set to True, proxy a remote graphical agent.

        TODO: check if this function work properly, does not know how the data are transfered.

        :param string graph_name: the remote graphical agent name
        """
        if self.corba:
            import rtt_interface_corba
            graph_p = rtt_interface_corba.GetProxy(graph_name, False)
            self.graph = xdefw.rtt.Task(graph_p, binding_class = xdefw.rtt.ObjectStringBinding, static_classes=['agent'])

            Lscenes = self.graph.s.Viewer.getSceneLabels()
            self.graph_scn = self.graph.s.Interface(Lscenes[0])
            if len(Lscenes) > 1:
                print "Warning: many graphical scenes found in new agent. Bind graph_scn with first: "+Lscenes[0]

        else:
            raise ImportError, "corba has not been selected"

    def createGlobalDistanceVisualizer(self):
        return collision.GlobalDistanceVisualizer("GlobalDistanceVisualizer", self.clock.s.getPeriod(), self)

    def addWorldToPhysic(self, new_world):
        """ Deserialize a new World into the physical components.

        It fills the phy, ms and xcd elements of the WorldManager instance.

        :param new_world: a world instance which will be deserialized
        :type  new_world: :class:`scene_pb2.World`
        """
        phy = self.phy
        scene = self.ms
        Lmat = new_world.scene.physical_scene.contact_materials
        for mat in Lmat:
            if mat in scene.getContactMaterials():
                new_world.scene.physical_scene.contact_materials.remove(mat)

        agents.physic.builder.deserializeWorld(self.phy, self.ms, self.xcd, new_world)

        while len(new_world.scene.physical_scene.contact_materials):
            new_world.scene.physical_scene.contact_materials.remove(new_world.scene.physical_scene.contact_materials[-1])
        new_world.scene.physical_scene.contact_materials.extend(Lmat)


    def addWorldToGraphic(self, new_world):
        """ Deserialize a new World into the graphical components.

        It fills the graph and graph_scn elements of the WorldManager instance.
        Note that if create_graphic has been set to False, nothing will be done.

        :param new_world: a world instance which will be deserialized
        :type  new_world: :class:`scene_pb2.World`
        """
        if self.graph is not None:
            agents.graphic.builder.deserializeWorld(self.graph, self.graph_scn, new_world)

            verbose_print("CREATE CONNECTION PHY/GRAPH...")
            ocb = self.phy.s.Connectors.OConnectorBodyStateList("ocb")
            for b in desc.physic.getRigidBodyNames(new_world.scene.physical_scene):
                ocb.addBody(b)



    def addWorld(self, new_world):
        """ Deserialize a new World into the graphical & physical components.

        :param new_world: a world instance which will be deserialized
        :type  new_world: :class:`scene_pb2.World`

        For more information, see methods:

        * :meth:`addWorldToPhysic`
        * :meth:`addWorldToGraphic`
        """
        phy_name = self.phy.getName()

        verbose_print("CREATE WORLD...")
        self.addWorldToPhysic(new_world)

        self.addWorldToGraphic(new_world)


    def removeWorldFromGraphic(self, old_world):
        """ Remove a World from all the graphical components.

        :param old_world: a world instance which will be deleted
        :type  old_world: :class:`scene_pb2.World`
        """
        if self.graph_scn is not None:
            verbose_print("REMOVE CONNECTION PHY/GRAPH...")
            ocb = self.phy.s.Connectors.OConnectorBodyStateList("ocb")

            #for b in old_world.scene.rigid_body_bindings:
            #    if len(b.graph_node) and len(b.rigid_body):
            #        ocb.removeBody(str(b.rigid_body))

            def deleteNodeInPhysicalAgent(node):
                for child in node.children:
                    deleteNodeInPhysicalAgent(child)
                body_name = node.rigid_body.name

                self.contact.removeAllInteractionsInvolving(str(body_name))
                ocb.removeBody(str(body_name))

            deleteNodeInPhysicalAgent(old_world.scene.physical_scene.nodes[0])

            verbose_print("REMOVE GRAPHICAL WORLD...")
            def deleteNodeInGraphicalAgent(node):
                for child in node.children:
                    deleteNodeInGraphicalAgent(child)
                nname = str(node.name)
                verbose_print('deleting '+nname)
                if self.graph_scn.SceneInterface.nodeExists(nname):
                    self.graph_scn.SceneInterface.removeNode(nname)

            deleteNodeInGraphicalAgent(old_world.scene.graphical_scene.root_node)

            verbose_print("REMOVE MARKERS...")
            markers = old_world.scene.graphical_scene.markers

            if not len(markers) == 0:
                for marker in markers:
                    if marker.name in self.graph_scn.MarkersInterface.getMarkerLabels():
                        verbose_print("Remove "+marker.name)
                        self.graph_scn.MarkersInterface.removeMarker(str(marker.name))


    def removeWorldFromPhysic(self, old_world):
        """ Remove a World from all the physical components.

        :param old_world: a world instance which will be deleted
        :type  old_world: :class:`scene_pb2.World`
        """
        phy = self.phy

        verbose_print("REMOVE PHYSICAL WORLD...")

        for mechanism in old_world.scene.physical_scene.mechanisms:
            mname = str(mechanism.name)
            self.phy.s.deleteComponent(mname)

        scene = self.ms
        def removeRigidBodyChildren(node):
            for child in node.children:
                removeRigidBodyChildren(child)
            verbose_print("deleting "+node.rigid_body.name)
            rbname = str(node.rigid_body.name)

            if rbname in scene.getBodyNames(): #TODO: Body and rigidBody, the same???
                scene.removeRigidBody(rbname)

            for to_del in [rbname, str(rbname+".comp"), str(node.inner_joint.name)]:
                if to_del in self.phy.s.getComponents():
                    self.phy.s.deleteComponent(to_del)

        for node in old_world.scene.physical_scene.nodes:
            removeRigidBodyChildren(node)

        verbose_print("REMOVE UNUSED MATERIAL...")
        scene.removeUnusedContactMaterials()


    def removeWorld(self, old_world):
        """ Remove a World from all the physical & graphical components.

        :param old_world: a scene_pb2.World which will be deleted
        :type  old_world: :class:`scene_pb2.World`
        """
        #delete interaction


        #delete graphical scene
        self.removeWorldFromGraphic(old_world)

        #delete physical scene
        self.removeWorldFromPhysic(old_world)


    def cleanGraph(self):
        """ Clean all components in the graphical scene.
        """
        if self.graph_scn is not None:
            self.graph_scn.SceneInterface.clearScene()
            self.graph_scn.MarkersInterface.clearMarkers()
            self.graph_scn.GlyphInterface.clearCollections()
            self.graph_scn.MaterialInterface.clearMaterials()


    def cleanPhy(self):
        """ Clean all components in the physical scene.
        """
        if(self.phy is not None):

            self.ms.clean()

            for kind in ["Robot", "RigidBody", "Composite"]:
                for c in [comp for comp in self.phy.s.getComponents() if self.phy.s.getType(comp) ==kind]:
                    self.phy.s.deleteComponent(c)
            for c in self.phy.s.getComponents():
                self.phy.s.deleteComponent(c)


    def stopSimulation(self):
        """ Stop simulation, whithout stopping physic agent.
        """
        self.phy.s.stopSimulation()

    def startSimulation(self):
        """ Start simulation when agent is already started, but the simulation has been stop with :meth:`stopSimulation`.
        """
        self.phy.s.startSimulation()

    def addMarkers(self, world, bodies_to_display=None, thin_markers=True):
        """ Add a visual frame to each body of bodies_to_display list.

        :param world: a world instance where are added the new markers
        :type  world: :class:`scene_pb2.World`
        :param list bodies_to_display: a list of body names one wants to display
        :param bool thin_markers: if True, displayed markers are three lines, else they are three big arrows

        If the list is empty, a visual frame is added for every body in world.
        This must be call before the :meth:`addWorld` method.
        """
        if self.graph_scn is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        allNodeNames = []
        def getNodeName(node):
            allNodeNames.append(node.rigid_body.name)

        if bodies_to_display is None:
            for child in world.scene.physical_scene.nodes:
                desc.core.visitDepthFirst(getNodeName, child)
            bodies_to_display = allNodeNames

        for body_name in bodies_to_display:
            if body_name not in self.graph_scn.MarkersInterface.getMarkerLabels():
                self.addFreeMarkers(world, str(body_name))
            else:
                verbose_print("Warning: "+body_name+" marker already exists. Nothing to do.")


    def createMarkerWorld(self, world_name, marker_name_list):
        """ Create a World which contains only markers.

        :param string world_name: the name given to the new created world
        :param list marker_name_list: a list of names representing the new created markers
        :rtype: a :class:`scene_pb2.World` which contains the new markers
        """
        marker_world = desc.scene.createWorld(name = world_name)
        self.addFreeMarkers(marker_world, marker_name_list)

        return marker_world


    def addMarkerToSimulation(self, name, thin_markers=True):
        """ Directly add a marker into the graphical scene.

        :param string name: the name of the new marker
        :param bool thin_markers: if True, displayed markers are three lines, else they are three big arrows
        """
        if self.graph_scn is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        self.graph_scn.MarkersInterface.addMarker(str(name), thin_markers)

    def removeMarkerFromSimulation(self, name):
        """ Directly remove a marker from the graphical scene.

        :param string name: the name of the marker one wants to delete
        """
        if self.graph_scn is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        self.graph_scn.MarkersInterface.removeMarker(str(name))

    def addFreeMarkers(self, world, marker_name_list):
        """ Add free markers into a world, whose positions are not related to bodies.

        :param world: a world instance where the marker will be added
        :type  world: :class:`scene_pb2.World`
        :param marker_name_list: it corresponds to the name(s) of the new marker(s)
        :type  marker_name_list: string or list of string

        In order to update its position, write [(Hxdes, marker_name), ..., (Hxdes2, marker_name2)] in a output port (name, "vector_pair_Displacementd_string")
        connected to graph.getPort("framePosition")
        """
        if not hasattr(marker_name_list, '__iter__'):
            marker_name_list = [marker_name_list]

        for marker_name in marker_name_list:
            marker = world.scene.graphical_scene.markers.add()
            marker.name = marker_name


    def removeMarkers(self, world, bodies_to_hide=None):
        """ Remove the visual frame attached to each body of bodies_to_display list.

        :param world: a world instance where the marker will be removed
        :type  world: :class:`scene_pb2.World`
        :param list bodies_to_hide: a list of body name one wants to hide

        If `bodies_to_hide` is None, visual frame for every body in world is removed.
        """
        if self.graph_scn is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        allNodeNames = []
        def getNodeName(node):
            allNodeNames.append(node.rigid_body.name)

        if bodies_to_hide is None:
            for child in world.scene.physical_scene.nodes:
                desc.core.visitDepthFirst(getNodeName, child)
            bodies_to_hide = allNodeNames

        for body_name in bodies_to_hide:
            if body_name in self.graph_scn.MarkersInterface.getMarkerLabels():
                self.graph_scn.MarkersInterface.removeMarker(str(body_name))
            else:
                verbose_print("Warning: "+body_name+" marker does not exist. Nothing to do.")

    ###########################################
    # method and shortcut to viewer interface #
    ###########################################
    def createWindow(self, windowName, width=800, height=600, x=0, y=0, viewPortName=None):
        """ Create a new visualization window.

        :param string windowName: the name (and title) given to the new window
        :param int width: the window width in pixel
        :param int height: the window height in pixel
        :param int x: the horizontal position of the window (in pixel, from left to right)
        :param int y: the vertical position of the window (in pixel, from top to bottom)
        :param string viewPortName: the name of the viewport created with the window; if None, it becomes windowName+".vp"
        """
        if self.graph is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        self.graph.s.Viewer.createOgreWindowAndInput(windowName)
        self.resizeWindow(windowName, width, height, x, y)
        if viewPortName is None:
            viewPortName = windowName+".vp"
        self.createViewPort(windowName, viewPortName)

    def createViewPort(self, windowName, viewportName, x=0, y=0, rx=1, ry=1, ratio=1, z=None):
        """ Create a new viewport in a defined window, to create multiple point of view.

        :param string windowName: the window name where the new viewport will be created
        :param string viewportName: the name of the created viewport
        :param double x: the horizontal position inside the window (ratio in [0,1], from left to right)
        :param double y: the vertical position inside the window (ratio in [0,1], from top to bottom)
        :param double rx: the width ratio [0,1] in the window
        :param double ry: the height ratio [0,1] in the window
        :param double ratio: the visualization ratio
        :param int z: the viewport depth, to manage viewports overlapping

        the x, y, rx & ry ratios respectively represent the horizontal position, vertical position,
        width and the height of the viewport inside the window.The are expressed in ratio between 0 and 1;
        the left-top corner is located at x=0,y=0 and the right-bottom corner is located at x=1,y=1.

        For instance, if one wants to create a viewport displayed in the half-top, half-right, the parameters
        should be set as follows::

            x=0.5, y=0, rx=0.5, ry=0.5

        The ratio argument can strech the view along x or y axis. TODO: explain more?

        The z argument is the viewport depth. Lower z are in the foreground, bigger z are in the background.
        """
        if self.graph is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        scene_name = Lscenes = self.graph.s.Viewer.getSceneLabels()[0]
        #TODO: warning if many getSceneLabels!!
        if z is None:
            z = self._internal_z
            self._internal_z += 1
        self.graph.s.Viewer.bindSceneWindow(scene_name, windowName, viewportName, z)
        self.graph_scn.CameraInterface.createCamera(viewportName+".cam")
        self.graph_scn.CameraInterface.switchToCamera(viewportName+".cam", viewportName)
        self.resizeViewport(viewportName, x,y, rx, ry, ratio)


    def resizeViewport(self, viewportName, x=0, y=0, rx=1, ry=1, ratio=1):
        """ Resize a previously created viewport.

        :param string viewportName: the name of the viewport one wants to modify
        :param double x: the horizontal position inside the window (ratio in [0,1], from left to right)
        :param double y: the vertical position inside the window (ratio in [0,1], from top to bottom)
        :param double rx: the width ratio [0,1] in the window
        :param double ry: the height ratio [0,1] in the window
        :param double ratio: the visualization ratio

        For more info on these arguments, see method :meth:`createViewPort`.
        """
        if self.graph is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        self.graph.s.Viewer.resizeViewport(viewportName, x,y,rx,ry)
        self.graph.s.Viewer.setViewportCustomRatio(viewportName, ratio)


    def resizeWindow(self, windowName, width=800, height=600, x=0, y=0):
        """ Resize a previously created window.

        :param string windowName: the name of the window one wants to modify
        :param int width: the window width in pixel
        :param int height: the window height in pixel
        :param int x: the horizontal position of the window (in pixel, from left to right)
        :param int y: the vertical position of the window (in pixel, from top to bottom)
        """
        if self.graph is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        self.graph.s.Viewer.resizeWindow(windowName, width, height)
        self.graph.s.Viewer.moveWindow(windowName, x, y)

    def attachViewPortToNode(self, viewportName, nodeName):
        """ Attach the viewport camera to a graphical node.

        :param string viewportName: the name of the viewport one wants to attach
        :param string nodeName: the graphical node which will support the viewport camera

        The camera will follow the node motion. Very useful, e.g. to simulate the visual data returned
        by a camera linked to the end effector of the robot.

        If I remember well, camera will look in the direction of axis -Z, and up along axis Y.
        """
        if self.graph_scn is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        self.graph_scn.CameraInterface.attachCameraToNode(viewportName+".cam", nodeName)

    def attachViewPortToNewNode(self, viewportName, parentNodeName, H):
        """ Attach the viewport camera to a node deported from a graphical node.

        :param string viewportName: the name of the viewport one wants to attach
        :param string parentNodeName: the graphical node which will be rigidly linked with the new graphical node
        :param H: the displacement from the parentNode to the new graph node which will support the viewport camera
        :type  H: :class:`lgsm.Displacement`

        If I remember well, camera will look in the direction of axis -Z, and up along axis Y.
        """
        if self.graph_scn is None:
            verbose_print("No graphic agent. Nothing to do.")
            return

        self.graph_scn.CameraInterface.attachCameraToNewNode(viewportName+".cam", parentNodeName, H)

