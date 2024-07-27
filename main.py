"""
Author: Tanner Dunworth
"""

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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



# region: |------------------ ACTIONS (Snipped from old script) ----------------| #



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




# endregion

#####################




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


# region: |----------- INTERFACE -------------| #


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
        
        _selectionInteractWidget = QtWidgets.QWidget()
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
      


class Section(QtWidgets.QWidget):
    
    def __init__(self, labelText, orientation, *args, **kwargs):
        super(Section, self).__init__(*args, **kwargs)
        
        self._sectionLayout = None
        
        _layout = QtWidgets.QVBoxLayout()
        _layout.setSpacing(3)
        _layout.setContentsMargins(0,0,0,0)
        self.setLayout(_layout)
        
        self._buildSection(labelText, orientation)
        
        
    def _buildSection(self, labelText, orientation):
        
        _sectionWidget = QtWidgets.QWidget()
        
        self._sectionLayout = QtWidgets.QVBoxLayout(_sectionWidget) if orientation == QtCore.Qt.Vertical else QtWidgets.QHBoxLayout(_sectionWidget)
        
        sectionLabel = QtWidgets.QLabel(text=labelText)
        
        self.layout().addWidget(sectionLabel, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.layout().addWidget(_sectionWidget)
        self._sectionLayout.addStretch(1)
        
        
    def addWidget(self, widget, *args, **kwargs):
        self._sectionLayout.insertWidget(0, widget, *args, **kwargs)
    

def cleanHistory():
    print("Clean History")
    return

# dict to define pipeline order



class SStep(QtCore.QObject):
    instanceCount = 0

    enterInterrupt = QtCore.Signal(list)
    exitInterrupt = QtCore.Signal(list)

    def __init__(self, name, callback):
        super(SStep, self).__init__()
        
        SStep.instanceCount += 1
        self.instanceId = self.getInstanceCount()

        self.buildData = None
        self.name = name
        self.callback = callback

    @classmethod
    def getInstanceCount(cls):
        return cls.instanceCount
    
    def getInstanceDataArray(self):
        return [self.instanceId, self.__class__.__name__]
    

    def run(self):
        print ('running', self.__class__.__name__)
        return


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

    def __init__(self):
        super(SCleanHistory, self).__init__(name="Clean History", callback=cleanHistory)

class SCleanNameSpace(SStep):

    def __init__(self):
        super(SCleanNameSpace, self).__init__(name="Clean History", callback=cleanHistory)

class SAssignShadingNetwork(SStep):

    def __init__(self):
        super(SAssignShadingNetwork, self).__init__(name="Clean History", callback=cleanHistory)

class SPivotsToOrigin(SStep):

    def __init__(self):
        super(SPivotsToOrigin, self).__init__(name="Clean History", callback=cleanHistory)


# region : cap

class SSetupWrapUvSet(SStep):

    def __init__(self):
        super(SSetupWrapUvSet, self).__init__(name="Clean History", callback=cleanHistory)
        # check for UV sets 
            # if additional set present **INTERUPT** ask user to verify if second set is valid
            # delete if not valid -- return otherwise
        # create new set
        # transfer attrs from buildData.headReferenceMesh
        # **INTERUPT** Open Uv editor for user to fix any edges in ear holes or mouth holes
        # **DONE

class SSetupWrapUvSet(SStep):

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



class SBuildData(QtCore.QObject):

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
        super(SBuildData, self).__init__()
        
        self.clothLodGroups = []
        self.wrapLodGroups = []
        self.simMeshes = []
        self.headReferenceMesh = None # could resolve from node names

class SBuildHandler(QtCore.QObject):
    runTriggered = QtCore.Signal(list)
    
    stepsUpdated = QtCore.Signal(list)
    stepInserted = QtCore.Signal(int, object)
    stepDeleted = QtCore.Signal(int)
    

    def __init__(self):
        super(SBuildHandler, self).__init__()

        self.buildData = SBuildData()
        self.buildRunner = SBuildRunner(self.buildData)
        
        self._workerThread = QtCore.QThread()
        
        self.runTriggered.connect(self.buildRunner.run)
        self.buildRunner.buildFinished.connect(self.handleBuildFinished)

        self.stepList = []

        self.inturruptDeque = []

    def insertStep(self, step, index):

        print("bs",self.buildData)
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
            raise ValueError("Given index is outside of step list range")
        self.stepList.pop(index)
        self.stepDeleted.emit(index)
        
        
    def moveStep(self, startIndex, endIndex):
        
        
        self.stepsUpdated.emit([startIndex, endIndex])
        return
    
########################

    @QtCore.Slot("")
    def handleInsertStepRequest(self, index):
        # take type

        step = SCleanHistory()
        self.insertStep(step, index)


    @QtCore.Slot("")
    def handleDeleteStepRequest(self, index):
        # take type

        self.deleteStep(index)



################
    def run(self):
        # QThread stuff then use inturrupt to pause 
        self.buildRunner.moveToThread(self._workerThread)
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
        for step in ssteps:
            step.run()
            self.sstepCompleted.emit(0, step.getInstanceDataArray())
            
        self.buildFinished.emit(0)

########### MAIN WINDOW ########################

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

class StackElement(QtWidgets.QWidget):
    
    
    def __init__(self, name="Step", *args, **kwargs):
        super(StackElement, self).__init__(*args, **kwargs)
        
        _layout = QtWidgets.QHBoxLayout()
        self.setLayout(_layout)
        
        
        self.nameLineEdit = QtWidgets.QLineEdit(text=name)
        self.layout().addWidget(self.nameLineEdit)
        
        
    def setName(self, name):
        self.nameLineEdit.setText(name)


class StackView(QtWidgets.QWidget):
    addButtonClicked = QtCore.Signal()
    deleteButtonClicked = QtCore.Signal()
    elementMoved = QtCore.Signal(int, int)
    updateRequest = QtCore.Signal(list)
    
    
    
    
    def __init__(self, *args, **kwargs):
        super(StackView, self).__init__(*args, **kwargs)
        
        self.stackScene = self.setupStackScene()
        self.toolbar = self.setupToolbar()
        
        _layout = QtWidgets.QVBoxLayout()
        self.setLayout(_layout)
        
        self.layout().addWidget(self.toolbar)
        self.layout().addWidget(self.stackScene)
        
        
    def setupStackScene(self):
        _layout = QtWidgets.QVBoxLayout()
        _layout.addStretch(1)

        widget = QtWidgets.QWidget()
        widget.setLayout(_layout)
        return widget

    def setupToolbar(self):
        _layout = QtWidgets.QHBoxLayout()
        widget = QtWidgets.QWidget()
        widget.setLayout(_layout)

        _addStep = QtWidgets.QPushButton(text="Add Step")
        _addStep.clicked.connect(self.addClickEvent)


        _deleteStep = QtWidgets.QPushButton(text="Delete Step")
        _deleteStep.clicked.connect(self.deleteClickEvent)


        for _widget in [_addStep, _deleteStep]:
            _layout.addWidget(_widget)

        return widget
    
    
    def elementAt(self, index):
        return self.stackScene.layout().itemAt(index).widget()


    # region: Update Ui Elements
        
    def insertStackElement(self, index, name):
        step = StackElement(name)
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
    
    def deleteClickEvent(self):
        self.deleteButtonClicked.emit()
    
    def addClickEvent(self):
        self.addButtonClicked.emit()


#endregion


class SNBuildViewer(QtWidgets.QWidget):
    # Only pass around indexes 
    insertStepRequest = QtCore.Signal(int)
    deleteStepRequest = QtCore.Signal(int)
    moveStepRequest = QtCore.Signal(int, int)
    updateStepRequest = QtCore.Signal(int, dict)
    
    def __init__(self, parent=None, *args, **kwargs):
        super(SNBuildViewer, self).__init__(parent=parent, *args, **kwargs)
        
        _centralLayout = QtWidgets.QVBoxLayout()
        _centralLayout.addStretch(1)
        _centralLayout.setContentsMargins(10,10,10,10)
        self.setLayout(_centralLayout)
        

        self._nodeView = self.setupNodeView()
        self._stackView = self.setupStackView()

        self.layout().addWidget(self._stackView)

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
        _view = StackView()

        _view.addButtonClicked.connect(self.handleAddButtonClick)
        _view.deleteButtonClicked.connect(self.handleDeleteButtonClick)

        return _view



    @QtCore.Slot("handleAddButtonClick")
    def handleAddButtonClick(self):
        self.insertStepRequest.emit(0)


    @QtCore.Slot("handleDeleteButtonClick")
    def handleDeleteButtonClick(self):
        self.deleteStepRequest.emit(0)

###############################################

    @QtCore.Slot("insertElement")
    def insertElement(self, data, index):
        self._stackView.insertStackElement(data, index)

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
            self._stackView.updateStackElement(index, data)



        
        
        
        
    
    




class MainWindow(QtWidgets.QDialog):
    _ClassId = "MMainWindow"
    
    def __new__(cls, parent=None, *args, **kwargs):
        if parent:
            for child in parent.children():
                if child.objectName() == MainWindow._ClassId:
                    s2.delete(child)
            
        if not hasattr(cls, 'instance'):
            cls.instance = super(MainWindow, cls).__new__(cls, *args, **kwargs)
        return cls.instance
    
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

        self.buildHandler.stepsUpdated.connect(self.buildViewer.updateElements)
        self.buildHandler.stepInserted.connect(self.buildViewer.insertElement)
        self.buildHandler.stepDeleted.connect(self.buildViewer.deleteElement)

        self.buildViewer.insertStepRequest.connect(self.buildHandler.handleInsertStepRequest)
        self.buildViewer.deleteStepRequest.connect(self.buildHandler.handleDeleteStepRequest)
        # self.buildViewer.moveStepRequest.connect(self.buildHandler.moveStepEvent)
        # _viewer.updateStepRequest.connect()

        self.layout().addWidget(self.buildViewer)
        # self.setupDialog()
        
        
    def addWidget(self, widget, *args, **kwargs):
        self.layout().insertWidget(0, widget)
        
        
    def mainGrpSelComponent(self):
        """
        Returns list with MDagPath or empty list
        """
        return self.mainGrpSelection.getSelComponents()
        
        
    def clothLodGrpSelComponent(self):
        """
        Returns list with MDagPath or empty list
        """
        return self.clothLodGrpSelection.getSelComponents()
        
        
        
    def setupDialog(self):
        
        
        # region: UTILITY
        
        clampLodInfluences = QtWidgets.QPushButton(text="Clamp LOD Influences")
        clampLodInfluences.clicked.connect(self.clampMainGrpLodInfluences)
        
        
        clampLodBlendWeights = QtWidgets.QPushButton(text="Clamp LOD Blend Weights")
        clampLodBlendWeights.clicked.connect(self.clampMainGrpClothBlendWeights)
        
        button = QtWidgets.QPushButton(text="Nothing Yet...")
    
        
        utilityWidgets = [
        clampLodInfluences,
        clampLodBlendWeights,
        button
        ]
        self.utilitiesSection = Section("Sing Use Utilities", QtCore.Qt.Horizontal)
        [self.utilitiesSection.addWidget(_widget) for _widget in utilityWidgets]
        self.addWidget(self.utilitiesSection)
        # endregion
        
        
        #region: PARAMS
        self.mainGrpSelection = CaptureSelectionWidget(title="Main Lod Group", mode=CaptureSelectionWidget.CurrentSingleSelection)
        self.capGrpSelection = CaptureSelectionWidget(title="Cap Lod Group", mode=CaptureSelectionWidget.CurrentSingleSelection)
        self.clothLodGrpSelection = CaptureSelectionWidget(title="Cloth Lod Group", mode=CaptureSelectionWidget.CurrentSingleSelection)
        self.clothGrpSelection = CaptureSelectionWidget(title="Cloth Sim Group", mode=CaptureSelectionWidget.CurrentSingleSelection)
        
        paramWidgets = [
                self.mainGrpSelection, 
                self.capGrpSelection, 
                self.clothLodGrpSelection,
                self.clothGrpSelection
                ]
        
        
        self.paramSection = Section("Parameters", QtCore.Qt.Vertical)
        [self.paramSection.addWidget(_widget) for _widget in paramWidgets]
        self.addWidget(self.paramSection)
        #endregion
        
        return   
        
        
    ####### TODO: Utility Methods -- Decouple into data class with signals at some point -- this is quicker for now
    
    def clampMainGrpLodInfluences(self):
        selComponent = self.mainGrpSelComponent()
        if len(selComponent) == 0:
            raise ValueError("No Main Group Has Been Specified!")
            return
            
        mainGrpName = selComponent[0].fullPathName()
        
        enforceInfluenceMaxOnLods(parentGroup=mainGrpName, lodInfluenceMaxes=lodWeightInfluenceMaxes)
        
    
    def clampMainGrpClothBlendWeights(self):
        selComponent = self.clothLodGrpSelComponent()
        if len(selComponent) == 0:
            raise ValueError("No Main Group Has Been Specified!")
            return
            
        grpName = selComponent[0].fullPathName()
        
        clampLodEaClothBlendweights(lodParentGroup=grpName)
        

#endregion

# om.MFnMesh
# om.MfnTransform

def combineGroupedMeshes(selectionList):
    
        
        
        
    for i in range(selectionList.length()):
        currentMDag = om.MDagPath()
        current = selectionList.getDagPath(i, currentMDag)
        currentType = currentMDag.apiType()
        
        if currentType not in [om.MFnMesh, om.MFnTransform]:
            return 





# region: Startup


def buildWindow(parent=None):
    _win = MainWindow(parent=parent)
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
    
    
if __name__ == "__main__":
    print('run')
    main(True)


