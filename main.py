"""
Author: Tanner Dunworth
"""
import sys
import logging
import ast
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


formatter = logging.Formatter("%(levelname)s | %(filename)s - %(funcName)s - %(lineno)d: %(message)s")
streamHandler = logging.StreamHandler(sys.stdout)
streamHandler.setFormatter(formatter)

logger.addHandler(streamHandler)

from shiboken2 import wrapInstance
import shiboken2 as s2
import sys, os
from collections import deque

from time import time

from PySide2 import QtWidgets, QtCore, QtGui
from functools import partial

sys.path.append("D:\\cadet2\\Bioware.MayaTools\\3.55.0\\2.7\\bioware\\python")
from pipeline import standalone

from collections import defaultdict


import maya.cmds as cmds
import maya.OpenMaya as om
import maya.OpenMayaUI as omui
from math import sqrt

devState = True

# TODO: Seperate into settings window
# region |------- CONSTANTS -----------|

# Starts from highest quality
lodWeightInfluenceMaxes = [8, 6, 4, 4, 2, 1]

#endregion


# region: ACTIONS
def isGeo(objectName):
    children = cmds.listRelatives(objectName, children=True, fullPath=True)
    if children is None or len(children) == 0:
        return False
    isAllShape = [cmds.objectType(child) == 'mesh' for child in children]

    if False in isAllShape:
        return False
    
    return True

def enforceInfluenceMaxOnLods(parentGroup, lodInfluenceMaxes):
    children = [child for child in cmds.listRelatives(parentGroup, children=True, fullPath=True) if "lod" in child]
    
    for child in children:
        _pathSplit = child.split("lod")
        if len(_pathSplit) == 0 or _pathSplit[-1].isnumeric() is False:
            print("Lod has no number: ", child)
            continue
        lodNumber = int(_pathSplit[-1])
        
        if lodNumber > len(lodInfluenceMaxes) - 1:
            print("Lod weight not described: ", child)
            continue
            
        lodMaxInfluence = lodInfluenceMaxes[lodNumber]
        
        meshes = [_child for _child in cmds.listRelatives(child, ad=True, fullPath=True) if isGeo(_child)]
        
        print "Enforcing max influence count of:",  lodMaxInfluence, "on mesh(es):", meshes
        try:
            bskcore.enforce_influence_max(dags=meshes, influence_max=lodMaxInfluence)
            print "Successfully enforced influences!"
        except Exception as e:
            print "Encountered exception while attempting to enforce max weights"
            print e

def clampEaClothBlendweights(mesh_shapes=None):
    if not mesh_shapes:
        mesh_shapes = cmds.ls(sl=True)
    for mesh_shape in mesh_shapes:
        try:
            values = cmds.getAttr(blendWeightAttr)
        except Exception as e:
            print "Caught Exception while getting 'blendWeights' attribute from {}".format(mesh_shape)
            continue
            
        blendWeightAttr = "{}.blendWeights".format(mesh_shape)
        cmds.setAttr(blendWeightAttr, lock=False)

        new_values = []
        for i in values:
            if i > 0.99:
            # print("{} is too big!".format(i))
                new_values.append(1.0)
            elif i < 0.001:
            # print("{} is too small!".format(i))
                new_values.append(0.0)
            else:
                new_values.append(i)
            
        cmds.setAttr("{}.blendWeights".format(mesh_shape), new_values, type="doubleArray")
    print('Finished clamping blend weights!')

def clampLodEaClothBlendweights(lodParentGroup):
    meshes = [child for child in cmds.listRelatives(lodParentGroup, ad=True, fullPath=True) if isGeo(child)]
    print(meshes)
    try:
        clampEaClothBlendweights(meshes)
    except Exception as e:
        print "Encountered exception when trying to clamp ea cloth blend weights:", e

def getClosestVertex(mDagPath, mPoint):
    """
    MDagPath
    MPoint
    """
    mMesh = om.MFnMesh(mDagPath)
    
    closestPoint = om.MPoint()
    
    mMesh.getClosestPoint(mPoint, closestPoint, om.MSpace.kWorld)
    
    return closestPoint

def snapTargetToClosestSourcePoints(sourceSelComponents, targetSelComponents, normalOffsetMagnitude):
    
    targetMDag = targetSelComponents[0]
    targetComponent = targetSelComponents[1]
    targetVertIter = om.MItMeshVertex(targetMDag, targetComponent)
    
    sourceMDagPath = sourceSelComponents[0]
    
    while not targetVertIter.isDone():
        
        targetPoint = targetVertIter.position(om.MSpace.kWorld)
        
        print targetVertIter.index(), "::", targetPoint.x, targetPoint.y, targetPoint.z, targetPoint.w
        
        closest = getClosestVertex(sourceMDagPath, targetPoint)
        
        targetVertIter.setPosition(closest, om.MSpace.kWorld)
        
        vertNormal = om.MVector()
        targetVertIter.getNormal(vertNormal, om.MSpace.kWorld)
        
        shortMDagPath = om.MDagPath()
        targetMDag.getPath(shortMDagPath)
        
        pathMString = shortMDagPath.fullPathName()
        
        vertString = "%s.vtx[%i]" % (pathMString, targetVertIter.count())
        
        cmds.moveVertexAlongDirection(
                    vertString,
                    direction=vertNormal.get(), 
                    magnitude=normalOffsetMagnitude
                    )
        
        next(targetVertIter)
    
    return 0

def snapTargetToSource(sourceSelComponents, targetSelComponents, normalOffsetMagnitude=0, mode="closestPoint"):
    """
        SelComponent: [om.MDagPath, om.MObject()]
    """
    
    if mode == "closestPoint":
        result = snapTargetToClosestSourcePoints(sourceSelComponents, targetSelComponents, normalOffsetMagnitude)
        print result    

def cacheMesh(targetNode, combineGroup=True):
    cacheName = targetNode + "__cache"
        
    if combineGroup and not isGeo(targetNode):
        _dupe = cmds.duplicate(targetNode, name=cacheName)[0]
        
        combineTargets = cmds.listRelatives(_dupe, allDescendents=True, fullPath=True, type='mesh')
        if isGeo(_dupe):
            combineTargets.append(_dupe)
        
        result = cmds.polyUnite(combineTargets, name=cacheName)[0]
        cmds.delete(result, constructionHistory=1)
        cmds.delete(_dupe)
        return result
        
        
    result = cmds.duplicate(targetNode, name=cacheName)[0]
    return result

def transferNormals(source, targets, cacheSource=False):
    sourceCache = cacheMesh(source) if cacheSource else source
    for target in targets:
        
        if cmds.objectType(target) != 'transform':
            print (target, "is not of type transform")
            continue
        
        if isGeo(target):
            cmds.transferAttributes(sourceCache, target, transferNormals=1)
            print ('Transfered normals from {} to {}'.format(source, target))
            continue
            
        children = cmds.listRelatives(target, children=True, fullPath=True)
        transferNormals(sourceCache, children, cacheSource=False)

def combineGroupedMeshes(selectionList):
    for i in range(selectionList.length()):
        currentMDag = om.MDagPath()
        current = selectionList.getDagPath(i, currentMDag)
        currentType = currentMDag.apiType()

        if currentType not in [om.MFnMesh, om.MFnTransform]:
            return

def cleanHistory():
    print("Clean History")
    return

#endregion


class MayaTypes:
    transform = "transform"
    mesh = 'mesh'
    joint = 'joint'



# region: |----------- INTERFACE -------------| #
class Widget(QtWidgets.QWidget):

    def __init__(self, *args, **kwargs):
        super(Widget, self).__init__(*args, **kwargs)

        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

class CaptureSelectionWidget(QtWidgets.QDialog):
    Mesh="MESH"
    Vert="VERT"
    CurrentSingleSelection="CURRENTSINGLE"
    
    
    
    def __init__(self, title="Target Vertices", mode="VERT", *args, **kwargs):
        super(CaptureSelectionWidget, self).__init__(*args, **kwargs)
        
        self.selComponents = None
        
        self.setupWidget(title, mode)


    def setupWidget(self, title, mode):
        _layout = QtWidgets.QHBoxLayout()
        self.setLayout(_layout)
        
        _selectionTitle = QtWidgets.QLabel(text=title)
        
        self.selectionDisplay = QtWidgets.QLineEdit(text="")
        self.selectionDisplay.setReadOnly(True)
        
        _selectionCaptureButton= QtWidgets.QPushButton(text="Capture")
        
        if mode == CaptureSelectionWidget.Vert:
            _selectionCaptureButton.clicked.connect(self.captureVertSelection)
        
        
        if mode == CaptureSelectionWidget.Mesh:
            _selectionCaptureButton.clicked.connect(self.captureMeshSelection)
            
        if mode == CaptureSelectionWidget.CurrentSingleSelection:
            _selectionCaptureButton.clicked.connect(self.captureCurrentSingleSelection)
            
        
        _selectionInteractLayout = QtWidgets.QHBoxLayout()
        _selectionInteractLayout.addWidget(self.selectionDisplay)
        _selectionInteractLayout.addWidget(_selectionCaptureButton, alignment=QtCore.Qt.AlignRight)
        
        _selectionInteractWidget = Widget()
        _selectionInteractWidget.setLayout(_selectionInteractLayout)
        
        
        self.layout().addWidget(_selectionTitle)
        self.layout().addWidget( _selectionInteractWidget)
        
        
    def captureCurrentSingleSelection(self):
        mSelList = om.MSelectionList()
        om.MGlobal.getActiveSelectionList(mSelList)
        
        dagPath = om.MDagPath()
        mSelList.getDagPath(0, dagPath)
            
            
        _tooltip = "DAG PATH: %s" % (dagPath.fullPathName())
        self.selectionDisplay.setToolTip(_tooltip)
        self.selectionDisplay.setText("%s [ %s ] " % ( dagPath.fullPathName().split("|")[-1], dagPath.node().apiTypeStr() ))
        
        # uses list like this because of issues reseting iterator when looping more than once
        self.selComponents = [dagPath]
        
        
    def captureVertSelection(self):
        _selection = cmds.ls(sl=True)
        
        mSelList = om.MSelectionList()
        om.MGlobal.getActiveSelectionList(mSelList)
        
        dagPath = om.MDagPath()
        component = om.MObject()
        mSelList.getDagPath(0, dagPath, component)
        
        if component.isNull():
            raise ValueError("Must have components selected to capture")
            
        vertIter = om.MItMeshVertex(dagPath, component)
            
        _tooltip = "DAG PATH: %s" % (dagPath.fullPathName())
        self.selectionDisplay.setToolTip(_tooltip)
        self.selectionDisplay.setText("Vert Count: [%s]" % (vertIter.count()))
        
        # uses list like this because of issues reseting iterator when looping more than once
        self.selComponents = [dagPath, component]
        
        
    def captureMeshSelection(self):
        _selection = cmds.ls(sl=True)
        
        mSelList = om.MSelectionList()
        om.MGlobal.getActiveSelectionList(mSelList)
        
        dagPath = om.MDagPath()
        mSelList.getDagPath(0, dagPath)
        
        if mSelList.length() < 1:
            raise ValueError("Must have components selected to capture")
            
            
        _tooltip = "DAG PATH: %s" % (dagPath.fullPathName())
        self.selectionDisplay.setToolTip(_tooltip)
        self.selectionDisplay.setText("Mesh Count: [%s]" % (mSelList.length()))
        
        # uses list like this because of issues reseting iterator when looping more than once
        self.selComponents = [dagPath]
        
    def getSelComponents(self):
        return self.selComponents


class Section(Widget):
    
    def __init__(self, labelText, orientation, *args, **kwargs):
        super(Section, self).__init__(*args, **kwargs)
        
        self._sectionLayout = None
        
        _layout = QtWidgets.QVBoxLayout()
        _layout.setSpacing(3)
        _layout.setContentsMargins(0,0,0,0)
        self.setLayout(_layout)
        
        self._buildSection(labelText, orientation)
        
        
    def _buildSection(self, labelText, orientation):
        
        _sectionWidget = Widget()
        
        self._sectionLayout = QtWidgets.QVBoxLayout(_sectionWidget) if orientation == QtCore.Qt.Vertical else QtWidgets.QHBoxLayout(_sectionWidget)
        
        sectionLabel = QtWidgets.QLabel(text=labelText)
        
        self.layout().addWidget(sectionLabel, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.layout().addWidget(_sectionWidget)
        self._sectionLayout.addStretch(1)
        
        
    def addWidget(self, widget, *args, **kwargs):
        self._sectionLayout.insertWidget(0, widget, *args, **kwargs)


# dict to define pipeline order

# region: STEPS
class SStep(QtCore.QObject):
    instanceCount = 0
    instanceType = "base"
    stepTypeList = []

    enterInterrupt = QtCore.Signal(list)
    exitInterrupt = QtCore.Signal(list)

    def __init__(self, name, typeStr):
        super(SStep, self).__init__()
        
        SStep.instanceCount += 1
        self.instanceId = self.getInstanceCount()

        self.stepConfigDisplayData = {}
        self.stepConfig = {}

        self.registerConfigDataEntry('Name', str)
        self.setConfigDataEntry('Name', name)

        self.registerConfigDataEntry("Step Type", str)
        self.setConfigDataEntry("Step Type", self.instanceType)

        self.buildData = None
        self.instanceType = typeStr
        self.name = name

    @classmethod
    def getInstanceCount(cls):
        return cls.instanceCount

    @classmethod
    def getInstanceType(cls):
        return cls.instanceType

    @classmethod
    def getStepList(cls):
        """
        Returns
        -------
        list: A list of names of all registered step types.

        """
        return
    
    def getInstanceDataArray(self):
        return [self.instanceId, self.__class__.__name__]
    

    def run(self):
        print ('running', self.__class__.__name__)
        return

    def registerConfigDataEntry(self, key, valueType):
        self.stepConfigDisplayData[key] = valueType

    def setConfigDataEntry(self, key, value):
        if not key in self.getConfigDisplayData().keys():
            logger.error("Given key: '{}' does not exist in registered config data".format(key))
            raise ValueError("Given key: '{}' does not exist in registered config data".format(key))
        if not isinstance(value, self.getConfigDisplayData().get(key)):
            msg = "Given value: '{}' does not match registered type: '{}'".format(value, self.getConfigDisplayData().get(key))
            logger.error(msg)
            raise TypeError(msg)

        self.stepConfig[key] = value

    def getConfigDisplayData(self):
        return self.stepConfigDisplayData

    def getConfigData(self):
        return self.stepConfig

    def setConfigData(self, configData):
        for key, value in configData.items():
            self.setConfigDataEntry(key, value)


    def registerBuildData(self, buildData):
        print(type(buildData))
        if not isinstance(buildData, SBuildData):
            raise TypeError("BuildData must be of type: 'BuildData'")
        self.buildData = buildData

    def enterInterrupt(self):
        self.enterInterrupt.emit(self.getInstanceDataArray())

    def exitInterrupt(self):
        self.exitInterrupt.emit(self.getInstanceDataArray())

class SCompoundStep(QtCore.QObject):
    instanceCount = 0
    instanceType = "Compund Step"

    enterInterrupt = QtCore.Signal(list)
    exitInterrupt = QtCore.Signal(list)

    def __init__(self, name, callback):
        super(SCompoundStep, self).__init__()
        
        SStep.instanceCount += 1
        self.instanceId = self.getInstanceCount()

        self.buildData = None
        self.name = name
        self.callback = callback

        self.exitInterrupt.emit(self.getInstanceDataArray())

class SCleanHistory(SStep):
    instanceType = "Clean History"

    def __init__(self):
        super(SCleanHistory, self).__init__(name="Clean History", typeStr="SCleanHistory")

        self.registerConfigDataEntry(key="Target Objects", valueType=list)
        self.setConfigDataEntry("Target Objects", ["main"])




class SCleanNameSpace(SStep):
    instanceType = "Clean Namespace"

    def __init__(self):
        super(SCleanNameSpace, self).__init__(name="Clean History", callback=cleanHistory)

class SAssignShadingNetwork(SStep):
    instanceType = "Update Shading Network"

    def __init__(self):
        super(SAssignShadingNetwork, self).__init__(name="Clean History", callback=cleanHistory)

class SPivotsToOrigin(SStep):
    instanceType = "Move Pivots To Origin"

    def __init__(self):
        super(SPivotsToOrigin, self).__init__(name="Clean History", callback=cleanHistory)


# region : cap

class SSetupWrapUvSet(SStep):
    instanceType = "Setup Wrapping UV Set"

    def __init__(self):
        super(SSetupWrapUvSet, self).__init__(name="Clean History", callback=cleanHistory)
        # check for UV sets 
            # if additional set present **INTERUPT** ask user to verify if second set is valid
            # delete if not valid -- return otherwise
        # create new set
        # transfer attrs from buildData.headReferenceMesh
        # **INTERUPT** Open Uv editor for user to fix any edges in ear holes or mouth holes
        # **DONE
        

#endregion

SStep.stepTypeList.append(SCleanHistory)
SStep.stepTypeList.append(SCleanNameSpace)
SStep.stepTypeList.append(SAssignShadingNetwork)
SStep.stepTypeList.append(SPivotsToOrigin)
SStep.stepTypeList.append(SSetupWrapUvSet)

class SBuildData(SStep):

    def __new__(cls, *args, **kwargs):
        instanceCount = 0
        if hasattr(cls, 'instance'):
            inst = getattr(cls, 'instance')
            print(inst)
        
        cls.instance = super(SBuildData, cls).__new__(cls, *args, **kwargs)
        return cls.instance

    def __init__(self):
        """
        Holds data necessary for steps to run.
        """
        super(SBuildData, self).__init__(name="Build Data", typeStr="SBuildData")
        
        self.clothLodGroups = []
        self.wrapLodGroups = []
        self.simMeshes = []
        self.headReferenceMesh = None # could resolve from node names

        self.registerConfigDataEntry(key="Cloth Lod Group", valueType=MayaTypes.transform)
        self.registerConfigDataEntry(key="Wrapping Lod Group", valueType=MayaTypes.transform)
        self.registerConfigDataEntry(key="Sim Group", valueType=MayaTypes.transform)
        self.registerConfigDataEntry(key="Reference Skeleton", valueType=MayaTypes.joint)


    def run(self):
        pass

class SBuildHandler(QtCore.QObject):
    runTriggered = QtCore.Signal(list)
    
    stepsUpdated = QtCore.Signal(list)
    stepInserted = QtCore.Signal(int, object)
    stepDeleted = QtCore.Signal(int)
    selectionData = QtCore.Signal(dict, dict)

    addStepDialogData = QtCore.Signal(list)

    stepStarted = QtCore.Signal(int)
    stepCompleted = QtCore.Signal(int)
    errorInBuild = QtCore.Signal(int)

    

    def __init__(self, *args, **kwargs):
        super(SBuildHandler, self).__init__(*args, **kwargs)

        self.buildData = SBuildData()
        self.buildRunner = SBuildRunner(self.buildData)
        self.buildRunner.sstepCompleted.connect(self.handleSStepComplete)

        self._selection = []
        
        self._workerThread = QtCore.QThread()
        
        self.runTriggered.connect(self.buildRunner.run)
        self.buildRunner.buildFinished.connect(self.handleBuildFinished)

        self.stepTypes = SStep.stepTypeList

        self.stepList = []
        self.paramEntityList = [self.buildData]

        self.inturruptDeque = []


    def insertStep(self, stepType, index):
        step = stepType()
        logger.debug("Inserting step: {} at index: {}".format(step, index))
        if not index:
            index = 0

        step.registerBuildData(self.buildData)

        # step.enterInterrupt.connect()
        # step.exitInterrupt.connect()

        self.stepList.insert(index, step)
        
        self.stepInserted.emit(index, step.name)
        return 0
    
    
    def deleteStep(self, index):
        if( index < 0 or index > len(self.stepList) - 1):
            raise ValueError("Given index: {} is outside of step list range".format(index))
        self.stepList.pop(index)
        self.stepDeleted.emit(index)
        
        
    def moveStep(self, startIndex, endIndex):
        updateList = []
        for i in range(startIndex, endIndex):
            _step = self.stepList[i]
            updateList.append( (i, _step.getConfigData()) )

        self.stepsUpdated.emit(updateList)

    def getStepIndex(self, stepInstanceId):
        for i, step in enumerate(self.stepList):
            if step.instanceId == stepInstanceId:
                return i

        return -1


# region: Runner Slots
    @QtCore.Slot("")
    def handleSStepComplete(self, exitCode, stepInstanceArray):
        index = self.getStepIndex(stepInstanceArray[0])
        if exitCode == 0:
            self.stepCompleted.emit(index)
            return

        self.errorInBuild.emit(index)



    @QtCore.Slot("")
    def handleSStepStart(self, stepInstanceArray):
        logger("Starting step: {}".format(stepInstanceArray))
        index = self.getStepIndex(stepInstanceArray[0])
        self.stepStarted.emit(index)

#endregion
########################
# region: View Slots

    @QtCore.Slot("")
    def handleAddStepDialogRequest(self):
        # take type
        self.addStepDialogData.emit(self.stepTypes)

    @QtCore.Slot("")
    def handleSaveStepConfigRequest(self, indexList, stepConfig):
        updateList = []
        for _step in self._selection:
            _step.setConfigData(stepConfig)

            _index = None
            if _step in self.paramEntityList:
                _index = (self.paramEntityList.index(_step)+1) * -1
            else:
                _index = self.stepList.index(_step)

            if not _index:
                pass

            updateList.append(( _index, _step.getConfigData() ))

        self.stepsUpdated.emit( updateList )

    @QtCore.Slot("")
    def handleDeleteStepRequest(self, indexList):
        # take type

        for index in sorted(indexList, reverse=1):
            self.deleteStep(index)

    def handleInitialDataRequest(self):
        for i, obj in enumerate(self.paramEntityList):
            self.stepInserted.emit((i+1)*-1, obj.name)

    @QtCore.Slot('')
    def handleStepSelectionRequest(self, indexList):
        configValues = {}
        displayConfig = {}
        steps = []
        _listToIndex = self.stepList
        for i in indexList:
            _index = i
            if i < 0:
                _index = abs(i) - 1
                _listToIndex = self.paramEntityList

            print i, _listToIndex
            _step = _listToIndex[_index]
            configValues.update(_step.getConfigData())
            displayConfig.update(_step.getConfigDisplayData())
            steps.append(_step)

        self._selection = steps
        self.selectionData.emit(displayConfig, configValues)
        pass


    @QtCore.Slot('')
    def handleBuildRequest(self):
        self.run()

# endregion
################

    def run(self):
        # QThread stuff then use inturrupt to pause
        logger.debug("Moving runner to worker thread and starting build.")
        self.buildRunner.moveToThread(self._workerThread)
        self._workerThread.start()
        self.runTriggered.emit(self.stepList)
        
    
    @QtCore.Slot()
    def handleBuildFinished(result):
        print("Build finished", result)


    @QtCore.Slot()
    def handleEnterInterrupt(self, instanceDataArray):
        self.inturruptDeque.insert(-1, instanceDataArray)
    
    @QtCore.Slot()
    def handleExitInterrupt(self, instanceDataArray):
        _index = self.inturruptDeque.index(instanceDataArray)
        self.inturruptDeque.pop(_index)


class SBuildRunner(QtCore.QObject):
    buildFinished = QtCore.Signal(int)
    sstepCompleted = QtCore.Signal(int, list)

    def __init__(self, buildData):
        super(SBuildRunner, self).__init__()
        self.buildData = buildData


    def run(self, ssteps):
        print('received')
        for step in ssteps:
            try:
                step.run()
                self.sstepCompleted.emit(0, step.getInstanceDataArray())
            except Exception as e:
                self.sstepCompleted.emit(1, step.getInstanceDataArray())
            
        self.buildFinished.emit(0)

#endregion

# region: NODE GRAPH

class NNodeOutlet(QtWidgets.QGraphicsEllipseItem):
    
    def __init__(self, *args, **kwargs):
        super(NNodeOutlet, self).__init__()

class NNodeBody(QtWidgets.QGraphicsRectItem):
    
    def __init__(self, *args, **kwargs):
        super(NNodeBody, self).__init__()

        self.setFlags(self.ItemIsSelectable | self.ItemIsMovable)
        
        
    def paint(self, painter, style, *args, **kwargs):
        brush = QtGui.QBrush(QtCore.Qt.blue)
        painter.setBrush(brush)
        return super(NNodeBody, self).paint(painter, style, *args, **kwargs)
        
        
        # self.setRect(-100, -100, 50, 50)

class NNode(QtWidgets.QGraphicsItemGroup):
    
    def __init__(self, *args, **kwargs):
        super(NNode, self).__init__()
        
        
        self.body = NNodeBody()
        print self.body.opaqueArea().boundingRect()
        
        self.addToGroup(self.body)
        self.setFlags(self.ItemIsSelectable | self.ItemIsMovable)

class NGraphView(QtWidgets.QGraphicsView):
    
    def __init__(self, *args, **kwargs):
        super(NGraphView, self).__init__()
        
        brush = QtGui.QBrush(QtCore.Qt.red)
        self.setBackgroundBrush(brush)
    
class NGraphScene(QtWidgets.QGraphicsScene):
    
    def __init__(self, *args, **kwargs):
        super(NGraphScene, self).__init__()
        
        
# endregion


# region: STACK VIEW

class LayoutSelectionEventHandler(QtCore.QObject):
    SingleSelection = "SINGLE"
    MultiSelection = "MULTI"


    selectionChanged = QtCore.Signal()

    def __init__(self, selectionMode=MultiSelection):
        super(LayoutSelectionEventHandler, self).__init__()
        self.selectionMode = selectionMode
        self.selectedObjects = []

    def eventFilter(self, qobject, qevent):
        if isinstance(qevent, QtGui.QMouseEvent):
            self.handleMouseEvent(qobject, qevent)

        return False

    def handleMouseEvent(self, qobject, qevent):
        if self.selectionMode == self.MultiSelection:
            self.handleMultiSelectionMouseEvent(qobject, qevent)
        if self.selectionMode == self.SingleSelection:
            self.handleSingleSelectionMouseEvent(qobject, qevent)

        return False

    def selectedStyle(self, objectName):

        objectSpecifier = "QObject"
        if objectName:
            objectSpecifier = "#{}".format(objectName)
        style = objectSpecifier + "{border: 2px solid light-blue; background-color: white}"
        return style

    def unselectedStyle(self, objectName):
        objectSpecifier = "QObject"
        if objectName:
            objectSpecifier = "#{}".format(objectName)
        style = objectSpecifier + "{border: 0px;}"
        return style

    def handleMultiSelectionMouseEvent(self, qobject, qevent):
        if qevent.type() == QtCore.QEvent.Type.MouseButtonPress:
            if not hasattr(qobject, "selected") or not qobject.selected:
                qobject.selected = True

                self.selectedObjects.append(qobject)

                qobject.setStyleSheet(self.selectedStyle(qobject.objectName()))
                logger.debug("QObject: {} -- [selected] attribute set to {}")

            else:
                qobject.selected = False
                self.selectedObjects.pop(self.selectedObjects.index(qobject))
                qobject.setStyleSheet(self.unselectedStyle(qobject.objectName()))
                logger.debug("QObject: {} -- Set to selected")

            self.selectionChanged.emit()
            logger.debug("QObject: [ {}.selected ] \t attribute set to {}".format(qobject, qobject.selected))

    def handleSingleSelectionMouseEvent(self, qobject, qevent):
        if qevent.type() == QtCore.QEvent.Type.MouseButtonPress:
            if not hasattr(qobject, "selected") or not qobject.selected:

                for obj in self.selectedObjects:
                    obj.selected=False
                    obj.setStyleSheet("border: 0px")
                    self.selectedObjects.remove(obj)

                qobject.selected = True
                self.selectedObjects.append(qobject)
                qobject.setStyleSheet(self.selectedStyle(qobject.objectName()))
                logger.debug("QObject: {} -- [selected] attribute set to {}")

            else:
                qobject.selected = False
                qobject.setStyleSheet(self.unselectedStyle(qobject.objectName()))

                self.selectedObjects = []

                logger.debug("QObject: {} -- Set to selected")

            self.selectionChanged.emit()
            logger.debug("QObject: [ {}.selected ] \t attribute set to {}".format(qobject, qobject.selected))

class StackElement(Widget):
    
    
    def __init__(self, name="Step", *args, **kwargs):
        super(StackElement, self).__init__(*args, **kwargs)
        self.setObjectName("StackElement")
        
        _layout = QtWidgets.QHBoxLayout()
        self.setLayout(_layout)
        
        self.nameLabel = QtWidgets.QLabel(text=name)

        self.layout().addWidget(self.nameLabel)
        
        
    def setName(self, name):

        self.nameLabel.setText(name.get("Step Name"))

class StackView(Widget):
    addButtonClicked = QtCore.Signal()
    deleteButtonClicked = QtCore.Signal(list)
    buildButtonClicked = QtCore.Signal()

    elementMoved = QtCore.Signal(int, int)
    updateRequest = QtCore.Signal(list)
    elementSelectionChanged = QtCore.Signal(list)
    
    
    
    
    def __init__(self, selectionEventFilter=None, *args, **kwargs):
        super(StackView, self).__init__(*args, **kwargs)
        self.setObjectName("StackView")

        self.selectionEventFilter = selectionEventFilter
        if not selectionEventFilter:
            self.selectionEventFilter = LayoutSelectionEventHandler()
        self.selectionEventFilter.selectionChanged.connect(self.handleSelectionChanged)

        self.stackScene = self.setupStackScene()
        self.stackScene.setObjectName("StackScene")
        self.stackScene.setAutoFillBackground(True)

        self.toolbar = self.setupToolbar()
        
        _layout = QtWidgets.QVBoxLayout()
        self.setLayout(_layout)
        
        self.layout().addWidget(self.toolbar, alignment=QtCore.Qt.AlignTop)
        self.layout().addWidget(self.stackScene)

    def setupStackScene(self):
        _layout = QtWidgets.QVBoxLayout()
        _layout.addStretch(1)

        widget = Widget()
        widget.setLayout(_layout)
        return widget

    def setupToolbar(self):
        _layout = QtWidgets.QHBoxLayout()
        widget = Widget()
        widget.setLayout(_layout)


        _buildStep = QtWidgets.QPushButton(text="Run Build")
        _buildStep.clicked.connect(self.buildClickEvent)

        _addStep = QtWidgets.QPushButton(text="Add Step")
        _addStep.clicked.connect(self.addClickEvent)


        _deleteStep = QtWidgets.QPushButton(text="Delete Step")
        _deleteStep.clicked.connect(self.deleteClickEvent)


        for _widget in [_buildStep, _addStep, _deleteStep]:
            _layout.addWidget(_widget)

        return widget
    
    
    def elementAt(self, index):
        return self.stackScene.layout().itemAt(index).widget()

    def selectedIndices(self):
        selectedIndices = []
        for i in range(0, self.stackScene.layout().count() - 1):
            _widget = self.elementAt(i)
            if not hasattr(_widget, 'selected'):
                continue
            if not _widget.selected:
                continue
            selectedIndices.append(i)
        return selectedIndices


    # region: Update Ui Elements

    @QtCore.Slot('')
    def handleSelectionChanged(self, *args):
        self.elementSelectionChanged.emit(self.selectedIndices())
        
    def insertStackElement(self, index, name):
        step = StackElement(name)
        step.installEventFilter(self.selectionEventFilter)
        self.stackScene.layout().insertWidget(index, step)

        logger.debug("Inserted '{}' into stack at index '{}'.".format(name, index))

    def deleteStackElement(self, index):
        element = self.elementAt(index)

        print(element)
        self.stackScene.layout().removeWidget(element)
        element.deleteLater()
        print(index)
        logger.info("Widget {} at index: {} removed!".format(element, index))

    def updateStackElement(self, index, data):
        _widget = self.elementAt(index)
        _widget.setName(data)

    # endregion
    
    
    #SIGNALS

    @QtCore.Slot('')
    def deleteClickEvent(self):
        self.deleteButtonClicked.emit(self.selectedIndices())

    @QtCore.Slot('')
    def addClickEvent(self):
        self.addButtonClicked.emit()

    @QtCore.Slot('')
    def buildClickEvent(self):
        self.buildButtonClicked.emit()


#endregion


# region: DETAIL PANEL
class StepSelector(QtWidgets.QDialog):
    stepTypeSelected = QtCore.Signal(object)

    def __init__(self, types, *args, **kwargs):
        super(StepSelector, self).__init__(*args, **kwargs)

        self.selectionEventFilter = LayoutSelectionEventHandler(selectionMode=LayoutSelectionEventHandler.SingleSelection)

        self.setLayout(QtWidgets.QVBoxLayout())

        self.typeLayout = QtWidgets.QVBoxLayout()
        _typeWidget = Widget()
        _typeWidget.setLayout(self.typeLayout)
        for type in types:
            _label = QtWidgets.QLabel(text=type.getInstanceType())
            _label.typeReference = type
            _label.installEventFilter(self.selectionEventFilter)
            self.typeLayout.addWidget(_label)

        selectButton = QtWidgets.QPushButton(text="Select")
        selectButton.clicked.connect(self.handleSelectButtonClick)
        cancelButton = QtWidgets.QPushButton(text="Cancel")
        cancelButton.clicked.connect(self.close)
        _buttonlayout = QtWidgets.QHBoxLayout()
        _buttonlayout.addWidget(selectButton)
        _buttonlayout.addWidget(cancelButton)
        _buttonWidget = Widget()
        _buttonWidget.setLayout(_buttonlayout)

        self.layout().addWidget(_typeWidget)
        self.layout().addWidget(_buttonWidget)

    def getSelectedType(self):
        for i in range(0, self.typeLayout.count() - 1):
            _widget = self.typeLayout.itemAt(i).widget()
            if not hasattr(_widget, 'selected'):
                continue
            if not _widget.selected:
                continue
            _type = _widget.typeReference
            return _type

    def handleSelectButtonClick(self):
        selectedType = self.getSelectedType()
        if selectedType:
            self.stepTypeSelected.emit(selectedType)
            self.close()
            return

        logger.error("Must select a step type.")
        return

class StepView(Widget):
    saveUpdatedDataRequest = QtCore.Signal(dict)

    def __init__(self, *args, **kwargs):
        super(StepView, self).__init__(*args, **kwargs)

        _layout = QtWidgets.QVBoxLayout()
        _layout.addStretch(1)
        self.setLayout(_layout)

        self.rawTextEdit = QtWidgets.QTextEdit()
        self.saveButton = QtWidgets.QPushButton(text="Save")
        self.saveButton.clicked.connect(self.handleSaveButtonClick)

        self.layout().insertWidget(0, self.saveButton, alignment=QtCore.Qt.AlignBottom)
        self.layout().insertWidget(0, self.rawTextEdit, alignment=QtCore.Qt.AlignTop)


    @QtCore.Slot('')
    def populatePanel(self, stepData):
        """

        Parameters
        ----------
        stepData: dict

        """
        # show steps data
        self.rawTextEdit.setText(str(stepData))


    def clearPanel(self):
        self.rawTextEdit.clear()


    @QtCore.Slot('')
    def handleSaveButtonClick(self):
        updatedStr = self.rawTextEdit.toPlainText()
        try:
            evalData = ast.literal_eval(updatedStr)

        except Exception as e:
            logger.warn("Error hit while attempting to convert config data to 'dict'")
            logger.debug(e)
            return

        self.saveUpdatedDataRequest.emit(evalData)

#endregion


class SNBuildViewer(Widget):
    initialDataRequest = QtCore.Signal()

    # Only pass around indexes
    buildRequest = QtCore.Signal()
    addStepDialogRequest = QtCore.Signal()
    deleteStepRequest = QtCore.Signal(list)
    addStepRequest = QtCore.Signal(object, int)

    saveStepConfigRequest = QtCore.Signal(list, dict)

    moveStepRequest = QtCore.Signal(int, int)
    updateStepRequest = QtCore.Signal(int, dict)

    stepSelectionRequest = QtCore.Signal(list)
    
    def __init__(self, parent=None, *args, **kwargs):
        super(SNBuildViewer, self).__init__(parent=parent, *args, **kwargs)
        
        _centralLayout = QtWidgets.QVBoxLayout()
        _centralLayout.addStretch(1)
        _centralLayout.setContentsMargins(10,10,10,10)
        self.setLayout(_centralLayout)

        self._nodeView = self.setupNodeView()
        self.stackSelectionEventFilter = LayoutSelectionEventHandler(selectionMode=LayoutSelectionEventHandler.SingleSelection)
        self._parameterView = self.setupParameterView()
        self._stackView = self.setupStackView()
        self._stackView.layout().insertWidget(1, self._parameterView, alignment=QtCore.Qt.AlignTop)

        self._stepView = self.setupStepView()

        self.layout().addWidget(self._stackView, stretch=1, alignment=QtCore.Qt.AlignTop)
        self.layout().addWidget(self._stepView, alignment=QtCore.Qt.AlignTop)

    def setupNodeView(self):
        self.view = NGraphView()
        self.scene = NGraphScene()
        # self.scene.setSceneRect(-150, -150, 150, 150)




        node = NNodeBody()
        self.scene.addItem(node)
        node.setPos(0,0)
        node.ensureVisible()
        node.setScale(1000)

        self.view.setScene(self.scene)

    def setupStackView(self):
        _view = StackView(selectionEventFilter=self.stackSelectionEventFilter)

        _view.setStyleSheet('#StackView {border: 2px solid dark-grey} #StackScene {border: 2px dotted grey};')
        _view.setAutoFillBackground(True)

        _view.addButtonClicked.connect(self.handleAddDialogClick)
        _view.buildButtonClicked.connect(self.handleBuildButtonClick)
        _view.deleteButtonClicked.connect(self.handleDeleteButtonClick)
        _view.elementSelectionChanged.connect(self.handleSelectionChange)

        _view.setMinimumHeight(600)

        return _view

    def setupParameterView(self):
        _view = StackView(selectionEventFilter=self.stackSelectionEventFilter)
        _view.setObjectName("paramStackView")
        _view.setStyleSheet('#paramStackView {border: 2px dotted red} #StackScene{border: 0px};')

        _view.toolbar.hide()
        _view.elementSelectionChanged.connect(partial(self.handleSelectionChange, parameter=True))

        return _view

    def setupStepView(self):
        _view = StepView()
        _view.saveUpdatedDataRequest.connect(self.handleSaveStepClick)
        return _view

    @QtCore.Slot("handleAddButtonClick")
    def handleSaveStepClick(self, configData):
        _indexList = self._stackView.selectedIndices()
        # TODO: Keep track of selection
        self.saveStepConfigRequest.emit(_indexList, configData)

    @QtCore.Slot("handleAddButtonClick")
    def handleAddDialogClick(self):
        self.addStepDialogRequest.emit()

    @QtCore.Slot("handleAddButtonClick")
    def handleStepTypeSelection(self, type):
        self.addStepRequest.emit(type)


    @QtCore.Slot("handleDeleteButtonClick")
    def handleBuildButtonClick(self):
        self.buildRequest.emit()


    @QtCore.Slot("handleDeleteButtonClick")
    def handleDeleteButtonClick(self, indexList):
        self.deleteStepRequest.emit(indexList)

    @QtCore.Slot('')
    def handleSelectionChange(self, selectedIndices, parameter=False):
        if parameter:
            newIndices = [i*-1 for i in selectedIndices]
            self.stepSelectionRequest.emit(newIndices)
            return

        self.stepSelectionRequest.emit(selectedIndices)

###############################################
    @QtCore.Slot("")
    def displayStepData(self, displayDataDict, valueDataDict):
        self._stepView.clearPanel()
        self._stepView.populatePanel(valueDataDict)


    @QtCore.Slot('')
    def handleAddStepDialogData(self, types):
        _stepSelector = StepSelector(types=types, parent=self)
        _stepSelector.stepTypeSelected.connect(self.handleAddStepRequest)
        _stepSelector.show()

    def handleAddStepRequest(self, type):
        selectedIndices = sorted(self._stackView.selectedIndices(), reverse=True)
        index = 0
        if selectedIndices:
            index = selectedIndices[-1]

        self.addStepRequest.emit(type, index)

    @QtCore.Slot("insertElement")
    def insertElement(self, index, data):
        logger.debug("Received signal to insert element at indes: '{}' with data: '{}'".format(index, data))
        if index < 0:
            self._parameterView.insertStackElement(index, data)
            return
        self._stackView.insertStackElement(index, data)

    @QtCore.Slot("deleteElement")
    def deleteElement(self, index):
        self._stackView.deleteStackElement(index)

    @QtCore.Slot("updateElements")
    def updateElements(self, updateList):
        """

        Parameters
        ----------
        updateList: list[(int, dict)]

        """
        # [ (INDEX: int, DATA: dict) ]
        for index, data in updateList:
            if index < 0:
                self._parameterView.updateStackElement(index, data)
                continue
            self._stackView.updateStackElement(index, data)





class MainWindow(QtWidgets.QDialog):
    _ClassId = "MMainWindow"
    
    def __init__(self, parent=None, *args, **kwargs):
        super(MainWindow, self).__init__(parent=parent, *args, **kwargs)
        
        self.setObjectName(self._ClassId)
        
        self.setWindowFlags(QtCore.Qt.Tool)
        self.setWindowTitle("Card Hair Pipeline")
        
        _centralLayout = QtWidgets.QVBoxLayout()
        _centralLayout.addStretch(1)
        _centralLayout.setContentsMargins(10,10,10,10)
        self.setLayout(_centralLayout)

        self.buildHandler = SBuildHandler()

        self.buildViewer = SNBuildViewer()

        self.connectSignals()

        # self.buildViewer.moveStepRequest.connect(self.buildHandler.moveStepEvent)

        self.layout().insertWidget(0, self.buildViewer, alignment=QtCore.Qt.AlignTop)
        # self.setupDialog()

    def connectSignals(self):

        self.buildHandler.stepsUpdated.connect(self.buildViewer.updateElements)
        self.buildHandler.stepInserted.connect(self.buildViewer.insertElement)
        self.buildHandler.stepDeleted.connect(self.buildViewer.deleteElement)
        self.buildHandler.selectionData.connect(self.buildViewer.displayStepData)
        self.buildHandler.addStepDialogData.connect(self.buildViewer.handleAddStepDialogData)

        self.buildViewer.initialDataRequest.connect(self.buildHandler.handleInitialDataRequest)
        self.buildViewer.addStepDialogRequest.connect(self.buildHandler.handleAddStepDialogRequest)
        self.buildViewer.deleteStepRequest.connect(self.buildHandler.handleDeleteStepRequest)
        self.buildViewer.stepSelectionRequest.connect(self.buildHandler.handleStepSelectionRequest)
        self.buildViewer.buildRequest.connect(self.buildHandler.handleBuildRequest)
        self.buildViewer.saveStepConfigRequest.connect(self.buildHandler.handleSaveStepConfigRequest)
        self.buildViewer.addStepRequest.connect(self.buildHandler.insertStep)

        self.buildViewer.initialDataRequest.emit()


    ####### TODO: Utility Methods -- Decouple into data class with signals at some point -- this is quicker for now


    def __new__(cls, parent=None, *args, **kwargs):
        if parent:
            for child in parent.children():
                if child.objectName() == MainWindow._ClassId:
                    s2.delete(child)

        if not hasattr(cls, 'instance'):
            cls.instance = super(MainWindow, cls).__new__(cls, *args, **kwargs)
        return cls.instance




# region: STARTUP

def buildWindow(parent=None):
    _win = MainWindow(parent=parent)
    _win.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
    return _win


def runStandalone():
    with standalone.run_maya_standalone():

        app = QtWidgets.QApplication.instance()
        if app is None:
            # if it does not exist then a QApplication is created
            app = QtWidgets.QApplication(sys.argv)

        win = buildWindow()
        win.show()

        app.exec_()


def runInMaya():
    
    win_ptr = omui.MQtUtil.mainWindow()
    mainWin = wrapInstance(long(win_ptr), QtWidgets.QMainWindow)
    
    win = buildWindow(mainWin)
    win.show()

    currentMSelList = om.MSelectionList()
    om.MGlobal.getActiveSelectionList(currentMSelList)
    
    

def main(standalone=False):

    ins1 = SCleanHistory()
    ins2 = SCleanHistory()
    ins = SCleanHistory()
    print(SCleanHistory.getInstanceCount())


    if standalone:
        runStandalone()
        return
    
    runInMaya()
# endregion
    
if __name__ == "__main__":
    print('run')
    main(True)
