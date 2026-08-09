# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'processed_results_tab.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
    QSpacerItem, QSplitter, QTabWidget, QVBoxLayout,
    QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(828, 580)
        self.horizontalLayout_4 = QHBoxLayout(Form)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.splitter = QSplitter(Form)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.verticalLayoutWidget = QWidget(self.splitter)
        self.verticalLayoutWidget.setObjectName(u"verticalLayoutWidget")
        self.verticalLayout = QVBoxLayout(self.verticalLayoutWidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.addSpectraButton = QPushButton(self.verticalLayoutWidget)
        self.addSpectraButton.setObjectName(u"addSpectraButton")

        self.horizontalLayout_3.addWidget(self.addSpectraButton)

        self.pushButton = QPushButton(self.verticalLayoutWidget)
        self.pushButton.setObjectName(u"pushButton")

        self.horizontalLayout_3.addWidget(self.pushButton)


        self.verticalLayout.addLayout(self.horizontalLayout_3)

        self.spectraList = QListWidget(self.verticalLayoutWidget)
        self.spectraList.setObjectName(u"spectraList")
        self.spectraList.setDragEnabled(True)

        self.verticalLayout.addWidget(self.spectraList)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.exportSelectedButton = QPushButton(self.verticalLayoutWidget)
        self.exportSelectedButton.setObjectName(u"exportSelectedButton")

        self.horizontalLayout.addWidget(self.exportSelectedButton)

        self.exportAllButton = QPushButton(self.verticalLayoutWidget)
        self.exportAllButton.setObjectName(u"exportAllButton")

        self.horizontalLayout.addWidget(self.exportAllButton)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.splitter.addWidget(self.verticalLayoutWidget)
        self.verticalLayoutWidget_2 = QWidget(self.splitter)
        self.verticalLayoutWidget_2.setObjectName(u"verticalLayoutWidget_2")
        self.verticalLayout_4 = QVBoxLayout(self.verticalLayoutWidget_2)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.verticalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.visualizationParamsTabWidget = QTabWidget(self.verticalLayoutWidget_2)
        self.visualizationParamsTabWidget.setObjectName(u"visualizationParamsTabWidget")
        self.dataDisplayTab = QWidget()
        self.dataDisplayTab.setObjectName(u"dataDisplayTab")
        self.verticalLayout_2 = QVBoxLayout(self.dataDisplayTab)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.normalizationComboBox = QComboBox(self.dataDisplayTab)
        self.normalizationComboBox.addItem("")
        self.normalizationComboBox.addItem("")
        self.normalizationComboBox.addItem("")
        self.normalizationComboBox.setObjectName(u"normalizationComboBox")
        self.normalizationComboBox.setMaximumSize(QSize(260, 16777215))

        self.verticalLayout_2.addWidget(self.normalizationComboBox)

        self.doubleSpinBox = QDoubleSpinBox(self.dataDisplayTab)
        self.doubleSpinBox.setObjectName(u"doubleSpinBox")
        self.doubleSpinBox.setEnabled(False)
        self.doubleSpinBox.setMaximumSize(QSize(120, 16777215))

        self.verticalLayout_2.addWidget(self.doubleSpinBox)

        self.horizontalLayout_7 = QHBoxLayout()
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.label = QLabel(self.dataDisplayTab)
        self.label.setObjectName(u"label")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy)

        self.horizontalLayout_7.addWidget(self.label)

        self.offsetSpectraSpinner = QDoubleSpinBox(self.dataDisplayTab)
        self.offsetSpectraSpinner.setObjectName(u"offsetSpectraSpinner")
        self.offsetSpectraSpinner.setMaximumSize(QSize(100, 16777215))

        self.horizontalLayout_7.addWidget(self.offsetSpectraSpinner)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_7.addItem(self.horizontalSpacer_2)


        self.verticalLayout_2.addLayout(self.horizontalLayout_7)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_2.addItem(self.verticalSpacer)

        self.visualizationParamsTabWidget.addTab(self.dataDisplayTab, "")
        self.hdComponentsTab = QWidget()
        self.hdComponentsTab.setObjectName(u"hdComponentsTab")
        self.verticalLayout_6 = QVBoxLayout(self.hdComponentsTab)
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.hdComponentGridLayout = QGridLayout()
        self.hdComponentGridLayout.setObjectName(u"hdComponentGridLayout")
        self.hdCheckReal = QCheckBox(self.hdComponentsTab)
        self.hdCheckReal.setObjectName(u"hdCheckReal")

        self.hdComponentGridLayout.addWidget(self.hdCheckReal, 0, 1, 1, 1)

        self.hdCheckHomodyne = QCheckBox(self.hdComponentsTab)
        self.hdCheckHomodyne.setObjectName(u"hdCheckHomodyne")

        self.hdComponentGridLayout.addWidget(self.hdCheckHomodyne, 1, 1, 1, 1)

        self.hdCheckPhase = QCheckBox(self.hdComponentsTab)
        self.hdCheckPhase.setObjectName(u"hdCheckPhase")

        self.hdComponentGridLayout.addWidget(self.hdCheckPhase, 1, 0, 1, 1)

        self.hdCheckImaginary = QCheckBox(self.hdComponentsTab)
        self.hdCheckImaginary.setObjectName(u"hdCheckImaginary")
        self.hdCheckImaginary.setChecked(True)

        self.hdComponentGridLayout.addWidget(self.hdCheckImaginary, 0, 0, 1, 1)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hdComponentGridLayout.addItem(self.horizontalSpacer, 1, 2, 1, 1)


        self.verticalLayout_6.addLayout(self.hdComponentGridLayout)

        self.hdCheckShowError = QCheckBox(self.hdComponentsTab)
        self.hdCheckShowError.setObjectName(u"hdCheckShowError")

        self.verticalLayout_6.addWidget(self.hdCheckShowError)

        self.verticalSpacer_2 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_6.addItem(self.verticalSpacer_2)

        self.visualizationParamsTabWidget.addTab(self.hdComponentsTab, "")
        self.colorsTab = QWidget()
        self.colorsTab.setObjectName(u"colorsTab")
        self.verticalLayout_5 = QVBoxLayout(self.colorsTab)
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.colorMapComboBox = QComboBox(self.colorsTab)
        self.colorMapComboBox.setObjectName(u"colorMapComboBox")
        self.colorMapComboBox.setMaximumSize(QSize(200, 16777215))

        self.verticalLayout_5.addWidget(self.colorMapComboBox)

        self.horizontalLayout_8 = QHBoxLayout()
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.colormapStartSpinner = QDoubleSpinBox(self.colorsTab)
        self.colormapStartSpinner.setObjectName(u"colormapStartSpinner")
        self.colormapStartSpinner.setEnabled(False)
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.colormapStartSpinner.sizePolicy().hasHeightForWidth())
        self.colormapStartSpinner.setSizePolicy(sizePolicy1)
        self.colormapStartSpinner.setMaximumSize(QSize(80, 16777215))
        self.colormapStartSpinner.setMaximum(1.000000000000000)
        self.colormapStartSpinner.setSingleStep(0.050000000000000)

        self.horizontalLayout_8.addWidget(self.colormapStartSpinner)

        self.colormapStopSpinner = QDoubleSpinBox(self.colorsTab)
        self.colormapStopSpinner.setObjectName(u"colormapStopSpinner")
        self.colormapStopSpinner.setEnabled(False)
        sizePolicy1.setHeightForWidth(self.colormapStopSpinner.sizePolicy().hasHeightForWidth())
        self.colormapStopSpinner.setSizePolicy(sizePolicy1)
        self.colormapStopSpinner.setMaximumSize(QSize(80, 16777215))
        self.colormapStopSpinner.setMaximum(1.000000000000000)
        self.colormapStopSpinner.setSingleStep(0.050000000000000)
        self.colormapStopSpinner.setValue(1.000000000000000)

        self.horizontalLayout_8.addWidget(self.colormapStopSpinner)

        self.horizontalSpacer_3 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_8.addItem(self.horizontalSpacer_3)


        self.verticalLayout_5.addLayout(self.horizontalLayout_8)

        self.verticalSpacer_3 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_5.addItem(self.verticalSpacer_3)

        self.visualizationParamsTabWidget.addTab(self.colorsTab, "")
        self.labelsTab = QWidget()
        self.labelsTab.setObjectName(u"labelsTab")
        self.verticalLayout_3 = QVBoxLayout(self.labelsTab)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.xAxisLabelLabel = QLabel(self.labelsTab)
        self.xAxisLabelLabel.setObjectName(u"xAxisLabelLabel")

        self.horizontalLayout_2.addWidget(self.xAxisLabelLabel)

        self.xAxisLabelEdit = QLineEdit(self.labelsTab)
        self.xAxisLabelEdit.setObjectName(u"xAxisLabelEdit")
        self.xAxisLabelEdit.setMaximumSize(QSize(220, 16777215))

        self.horizontalLayout_2.addWidget(self.xAxisLabelEdit)

        self.horizontalSpacer_4 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_4)


        self.verticalLayout_3.addLayout(self.horizontalLayout_2)

        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.yAxisLabelLabel = QLabel(self.labelsTab)
        self.yAxisLabelLabel.setObjectName(u"yAxisLabelLabel")

        self.horizontalLayout_5.addWidget(self.yAxisLabelLabel)

        self.yAxisLabelEdit = QLineEdit(self.labelsTab)
        self.yAxisLabelEdit.setObjectName(u"yAxisLabelEdit")
        self.yAxisLabelEdit.setMaximumSize(QSize(220, 16777215))

        self.horizontalLayout_5.addWidget(self.yAxisLabelEdit)

        self.horizontalSpacer_5 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_5.addItem(self.horizontalSpacer_5)


        self.verticalLayout_3.addLayout(self.horizontalLayout_5)

        self.horizontalLayout_6 = QHBoxLayout()
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.legendFieldLabel = QLabel(self.labelsTab)
        self.legendFieldLabel.setObjectName(u"legendFieldLabel")

        self.horizontalLayout_6.addWidget(self.legendFieldLabel)

        self.legendFieldComboBox = QComboBox(self.labelsTab)
        self.legendFieldComboBox.setObjectName(u"legendFieldComboBox")
        self.legendFieldComboBox.setMaximumSize(QSize(200, 16777215))

        self.horizontalLayout_6.addWidget(self.legendFieldComboBox)

        self.horizontalSpacer_6 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_6.addItem(self.horizontalSpacer_6)


        self.verticalLayout_3.addLayout(self.horizontalLayout_6)

        self.horizontalLayout_9 = QHBoxLayout()
        self.horizontalLayout_9.setObjectName(u"horizontalLayout_9")
        self.annotationsButton = QPushButton(self.labelsTab)
        self.annotationsButton.setObjectName(u"annotationsButton")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.annotationsButton.sizePolicy().hasHeightForWidth())
        self.annotationsButton.setSizePolicy(sizePolicy2)

        self.horizontalLayout_9.addWidget(self.annotationsButton)

        self.horizontalSpacer_7 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_9.addItem(self.horizontalSpacer_7)


        self.verticalLayout_3.addLayout(self.horizontalLayout_9)

        self.verticalSpacer_4 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_3.addItem(self.verticalSpacer_4)

        self.visualizationParamsTabWidget.addTab(self.labelsTab, "")

        self.verticalLayout_4.addWidget(self.visualizationParamsTabWidget)

        self.plotWidget = QWidget(self.verticalLayoutWidget_2)
        self.plotWidget.setObjectName(u"plotWidget")

        self.verticalLayout_4.addWidget(self.plotWidget)

        self.splitter.addWidget(self.verticalLayoutWidget_2)

        self.horizontalLayout_4.addWidget(self.splitter)


        self.retranslateUi(Form)

        self.visualizationParamsTabWidget.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.addSpectraButton.setText(QCoreApplication.translate("Form", u"Add spectra from file", None))
        self.pushButton.setText(QCoreApplication.translate("Form", u"Sort by metadata", None))
        self.exportSelectedButton.setText(QCoreApplication.translate("Form", u"Export selected", None))
        self.exportAllButton.setText(QCoreApplication.translate("Form", u"Export all", None))
        self.normalizationComboBox.setItemText(0, QCoreApplication.translate("Form", u"Plot \"as is\"", None))
        self.normalizationComboBox.setItemText(1, QCoreApplication.translate("Form", u"Normalize to given wavenumber", None))
        self.normalizationComboBox.setItemText(2, QCoreApplication.translate("Form", u"Normalize to highest peak", None))

        self.label.setText(QCoreApplication.translate("Form", u"Offset:", None))
        self.visualizationParamsTabWidget.setTabText(self.visualizationParamsTabWidget.indexOf(self.dataDisplayTab), QCoreApplication.translate("Form", u"Data display", None))
        self.hdCheckReal.setText(QCoreApplication.translate("Form", u"Real", None))
        self.hdCheckHomodyne.setText(QCoreApplication.translate("Form", u"|\u03c7\u207d\u00b2\u207e|\u00b2 (Homodyne)", None))
        self.hdCheckPhase.setText(QCoreApplication.translate("Form", u"Phase", None))
        self.hdCheckImaginary.setText(QCoreApplication.translate("Form", u"Imaginary", None))
        self.hdCheckShowError.setText(QCoreApplication.translate("Form", u"Show error", None))
        self.visualizationParamsTabWidget.setTabText(self.visualizationParamsTabWidget.indexOf(self.hdComponentsTab), QCoreApplication.translate("Form", u"HD-SFG components", None))
        self.visualizationParamsTabWidget.setTabText(self.visualizationParamsTabWidget.indexOf(self.colorsTab), QCoreApplication.translate("Form", u"Colors", None))
        self.xAxisLabelLabel.setText(QCoreApplication.translate("Form", u"X axis label:", None))
        self.yAxisLabelLabel.setText(QCoreApplication.translate("Form", u"Y axis label:", None))
        self.legendFieldLabel.setText(QCoreApplication.translate("Form", u"Legend:", None))
        self.annotationsButton.setText(QCoreApplication.translate("Form", u"Annotations...", None))
        self.visualizationParamsTabWidget.setTabText(self.visualizationParamsTabWidget.indexOf(self.labelsTab), QCoreApplication.translate("Form", u"Labels, legend && annotations", None))
    # retranslateUi

