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
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSizePolicy,
    QSpacerItem, QSplitter, QVBoxLayout, QWidget)

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
        self.visualizationParamsGroupBox = QGroupBox(self.verticalLayoutWidget_2)
        self.visualizationParamsGroupBox.setObjectName(u"visualizationParamsGroupBox")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.visualizationParamsGroupBox.sizePolicy().hasHeightForWidth())
        self.visualizationParamsGroupBox.setSizePolicy(sizePolicy)
        font = QFont()
        font.setBold(False)
        self.visualizationParamsGroupBox.setFont(font)
        self.horizontalLayout_2 = QHBoxLayout(self.visualizationParamsGroupBox)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.frame = QFrame(self.visualizationParamsGroupBox)
        self.frame.setObjectName(u"frame")
        sizePolicy.setHeightForWidth(self.frame.sizePolicy().hasHeightForWidth())
        self.frame.setSizePolicy(sizePolicy)
        self.frame.setFrameShape(QFrame.StyledPanel)
        self.frame.setFrameShadow(QFrame.Raised)
        self.verticalLayout_2 = QVBoxLayout(self.frame)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.normalizationComboBox = QComboBox(self.frame)
        self.normalizationComboBox.addItem("")
        self.normalizationComboBox.addItem("")
        self.normalizationComboBox.addItem("")
        self.normalizationComboBox.setObjectName(u"normalizationComboBox")

        self.verticalLayout_2.addWidget(self.normalizationComboBox)

        self.doubleSpinBox = QDoubleSpinBox(self.frame)
        self.doubleSpinBox.setObjectName(u"doubleSpinBox")
        self.doubleSpinBox.setEnabled(False)

        self.verticalLayout_2.addWidget(self.doubleSpinBox)


        self.horizontalLayout_2.addWidget(self.frame)

        self.frame_2 = QFrame(self.visualizationParamsGroupBox)
        self.frame_2.setObjectName(u"frame_2")
        sizePolicy.setHeightForWidth(self.frame_2.sizePolicy().hasHeightForWidth())
        self.frame_2.setSizePolicy(sizePolicy)
        self.frame_2.setFrameShape(QFrame.StyledPanel)
        self.frame_2.setFrameShadow(QFrame.Raised)
        self.gridLayout = QGridLayout(self.frame_2)
        self.gridLayout.setObjectName(u"gridLayout")
        self.colorMapComboBox = QComboBox(self.frame_2)
        self.colorMapComboBox.setObjectName(u"colorMapComboBox")

        self.gridLayout.addWidget(self.colorMapComboBox, 0, 0, 1, 2)

        self.colormapStartSpinner = QDoubleSpinBox(self.frame_2)
        self.colormapStartSpinner.setObjectName(u"colormapStartSpinner")
        self.colormapStartSpinner.setEnabled(False)
        self.colormapStartSpinner.setMaximum(1.000000000000000)
        self.colormapStartSpinner.setSingleStep(0.050000000000000)

        self.gridLayout.addWidget(self.colormapStartSpinner, 1, 0, 1, 1)

        self.colormapStopSpinner = QDoubleSpinBox(self.frame_2)
        self.colormapStopSpinner.setObjectName(u"colormapStopSpinner")
        self.colormapStopSpinner.setEnabled(False)
        self.colormapStopSpinner.setMaximum(1.000000000000000)
        self.colormapStopSpinner.setSingleStep(0.050000000000000)
        self.colormapStopSpinner.setValue(1.000000000000000)

        self.gridLayout.addWidget(self.colormapStopSpinner, 1, 1, 1, 1)


        self.horizontalLayout_2.addWidget(self.frame_2)

        self.verticalLayout_5 = QVBoxLayout()
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.frame_3 = QFrame(self.visualizationParamsGroupBox)
        self.frame_3.setObjectName(u"frame_3")
        sizePolicy.setHeightForWidth(self.frame_3.sizePolicy().hasHeightForWidth())
        self.frame_3.setSizePolicy(sizePolicy)
        self.frame_3.setFrameShape(QFrame.StyledPanel)
        self.frame_3.setFrameShadow(QFrame.Raised)
        self.verticalLayout_3 = QVBoxLayout(self.frame_3)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.label = QLabel(self.frame_3)
        self.label.setObjectName(u"label")
        sizePolicy.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy)

        self.verticalLayout_3.addWidget(self.label)

        self.offsetSpectraSpinner = QDoubleSpinBox(self.frame_3)
        self.offsetSpectraSpinner.setObjectName(u"offsetSpectraSpinner")

        self.verticalLayout_3.addWidget(self.offsetSpectraSpinner)


        self.verticalLayout_5.addWidget(self.frame_3)

        self.verticalSpacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_5.addItem(self.verticalSpacer)


        self.horizontalLayout_2.addLayout(self.verticalLayout_5)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer)


        self.verticalLayout_4.addWidget(self.visualizationParamsGroupBox)

        self.plotWidget = QWidget(self.verticalLayoutWidget_2)
        self.plotWidget.setObjectName(u"plotWidget")

        self.verticalLayout_4.addWidget(self.plotWidget)

        self.splitter.addWidget(self.verticalLayoutWidget_2)

        self.horizontalLayout_4.addWidget(self.splitter)


        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.addSpectraButton.setText(QCoreApplication.translate("Form", u"Add spectra from file", None))
        self.pushButton.setText(QCoreApplication.translate("Form", u"Sort by metadata", None))
        self.exportSelectedButton.setText(QCoreApplication.translate("Form", u"Export selected", None))
        self.exportAllButton.setText(QCoreApplication.translate("Form", u"Export all", None))
        self.visualizationParamsGroupBox.setTitle(QCoreApplication.translate("Form", u"Visualization parameters", None))
        self.normalizationComboBox.setItemText(0, QCoreApplication.translate("Form", u"Plot \"as is\"", None))
        self.normalizationComboBox.setItemText(1, QCoreApplication.translate("Form", u"Normalize to given wavenumber", None))
        self.normalizationComboBox.setItemText(2, QCoreApplication.translate("Form", u"Normalize to highest peak", None))

        self.label.setText(QCoreApplication.translate("Form", u"Offset:", None))
    # retranslateUi

