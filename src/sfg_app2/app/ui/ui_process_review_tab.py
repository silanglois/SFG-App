# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'process_review_tab.ui'
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
    QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QRadioButton, QSizePolicy, QSpacerItem, QSplitter,
    QVBoxLayout, QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(867, 580)
        self.verticalLayout_2 = QVBoxLayout(Form)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.calibrationFrame = QFrame(Form)
        self.calibrationFrame.setObjectName(u"calibrationFrame")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.calibrationFrame.sizePolicy().hasHeightForWidth())
        self.calibrationFrame.setSizePolicy(sizePolicy)
        self.calibrationFrame.setFrameShape(QFrame.StyledPanel)
        self.calibrationFrame.setFrameShadow(QFrame.Raised)
        self.horizontalLayout = QHBoxLayout(self.calibrationFrame)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.label = QLabel(self.calibrationFrame)
        self.label.setObjectName(u"label")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy1)
        self.label.setMaximumSize(QSize(16777215, 16777215))

        self.horizontalLayout.addWidget(self.label)

        self.upconversionSpinBox = QDoubleSpinBox(self.calibrationFrame)
        self.upconversionSpinBox.setObjectName(u"upconversionSpinBox")
        self.upconversionSpinBox.setDecimals(2)
        self.upconversionSpinBox.setMinimum(400.000000000000000)
        self.upconversionSpinBox.setMaximum(1400.000000000000000)
        self.upconversionSpinBox.setSingleStep(2.000000000000000)
        self.upconversionSpinBox.setValue(1030.700000000000045)

        self.horizontalLayout.addWidget(self.upconversionSpinBox)

        self.calibrateButton = QPushButton(self.calibrationFrame)
        self.calibrateButton.setObjectName(u"calibrateButton")

        self.horizontalLayout.addWidget(self.calibrateButton)

        self.horizontalSpacer = QSpacerItem(40, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)


        self.verticalLayout_2.addWidget(self.calibrationFrame)

        self.splitter = QSplitter(Form)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.leftPanelWidget = QWidget(self.splitter)
        self.leftPanelWidget.setObjectName(u"leftPanelWidget")
        self.verticalLayout = QVBoxLayout(self.leftPanelWidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.reviewReferencesButton = QPushButton(self.leftPanelWidget)
        self.reviewReferencesButton.setObjectName(u"reviewReferencesButton")

        self.verticalLayout.addWidget(self.reviewReferencesButton)

        self.label_2 = QLabel(self.leftPanelWidget)
        self.label_2.setObjectName(u"label_2")
        font = QFont()
        font.setBold(True)
        self.label_2.setFont(font)

        self.verticalLayout.addWidget(self.label_2)

        self.matchedSetsListWidget = QListWidget(self.leftPanelWidget)
        self.matchedSetsListWidget.setObjectName(u"matchedSetsListWidget")

        self.verticalLayout.addWidget(self.matchedSetsListWidget)

        self.setStatusLabel = QLabel(self.leftPanelWidget)
        self.setStatusLabel.setObjectName(u"setStatusLabel")
        self.setStatusLabel.setWordWrap(True)

        self.verticalLayout.addWidget(self.setStatusLabel)

        self.splitter.addWidget(self.leftPanelWidget)
        self.rightPanelWidget = QWidget(self.splitter)
        self.rightPanelWidget.setObjectName(u"rightPanelWidget")
        self.verticalLayout_3 = QVBoxLayout(self.rightPanelWidget)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.verticalLayout_5 = QVBoxLayout()
        self.verticalLayout_5.setObjectName(u"verticalLayout_5")
        self.label_3 = QLabel(self.rightPanelWidget)
        self.label_3.setObjectName(u"label_3")
        sizePolicy.setHeightForWidth(self.label_3.sizePolicy().hasHeightForWidth())
        self.label_3.setSizePolicy(sizePolicy)

        self.verticalLayout_5.addWidget(self.label_3)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.singleViewRadio = QRadioButton(self.rightPanelWidget)
        self.singleViewRadio.setObjectName(u"singleViewRadio")
        self.singleViewRadio.setChecked(True)

        self.horizontalLayout_3.addWidget(self.singleViewRadio)

        self.compareViewRadio = QRadioButton(self.rightPanelWidget)
        self.compareViewRadio.setObjectName(u"compareViewRadio")

        self.horizontalLayout_3.addWidget(self.compareViewRadio)


        self.verticalLayout_5.addLayout(self.horizontalLayout_3)


        self.horizontalLayout_2.addLayout(self.verticalLayout_5)

        self.stepSelectorFrame = QFrame(self.rightPanelWidget)
        self.stepSelectorFrame.setObjectName(u"stepSelectorFrame")
        sizePolicy.setHeightForWidth(self.stepSelectorFrame.sizePolicy().hasHeightForWidth())
        self.stepSelectorFrame.setSizePolicy(sizePolicy)
        self.stepSelectorFrame.setFrameShape(QFrame.StyledPanel)
        self.stepSelectorFrame.setFrameShadow(QFrame.Raised)
        self.verticalLayout_4 = QVBoxLayout(self.stepSelectorFrame)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.label_4 = QLabel(self.stepSelectorFrame)
        self.label_4.setObjectName(u"label_4")

        self.verticalLayout_4.addWidget(self.label_4)

        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.rawStepRadio = QRadioButton(self.stepSelectorFrame)
        self.rawStepRadio.setObjectName(u"rawStepRadio")
        self.rawStepRadio.setChecked(True)

        self.horizontalLayout_4.addWidget(self.rawStepRadio)

        self.despikedStepRadio = QRadioButton(self.stepSelectorFrame)
        self.despikedStepRadio.setObjectName(u"despikedStepRadio")

        self.horizontalLayout_4.addWidget(self.despikedStepRadio)

        self.averagedStepRadio = QRadioButton(self.stepSelectorFrame)
        self.averagedStepRadio.setObjectName(u"averagedStepRadio")

        self.horizontalLayout_4.addWidget(self.averagedStepRadio)

        self.bgSubtractedStepRadio = QRadioButton(self.stepSelectorFrame)
        self.bgSubtractedStepRadio.setObjectName(u"bgSubtractedStepRadio")

        self.horizontalLayout_4.addWidget(self.bgSubtractedStepRadio)

        self.normalizedStepRadio = QRadioButton(self.stepSelectorFrame)
        self.normalizedStepRadio.setObjectName(u"normalizedStepRadio")

        self.horizontalLayout_4.addWidget(self.normalizedStepRadio)


        self.verticalLayout_4.addLayout(self.horizontalLayout_4)


        self.horizontalLayout_2.addWidget(self.stepSelectorFrame)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)

        self.processAllButton = QPushButton(self.rightPanelWidget)
        self.processAllButton.setObjectName(u"processAllButton")

        self.horizontalLayout_2.addWidget(self.processAllButton)


        self.verticalLayout_3.addLayout(self.horizontalLayout_2)

        self.plotPlaceholder = QWidget(self.rightPanelWidget)
        self.plotPlaceholder.setObjectName(u"plotPlaceholder")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.plotPlaceholder.sizePolicy().hasHeightForWidth())
        self.plotPlaceholder.setSizePolicy(sizePolicy2)

        self.verticalLayout_3.addWidget(self.plotPlaceholder)

        self.bgCorrectionGroupBox = QGroupBox(self.rightPanelWidget)
        self.bgCorrectionGroupBox.setObjectName(u"bgCorrectionGroupBox")
        self.bgCorrectionGroupBox.setCheckable(True)
        self.bgCorrectionGroupBox.setChecked(False)
        self.gridLayout = QGridLayout(self.bgCorrectionGroupBox)
        self.gridLayout.setObjectName(u"gridLayout")
        self.signalOffsetCombo = QComboBox(self.bgCorrectionGroupBox)
        self.signalOffsetCombo.addItem("")
        self.signalOffsetCombo.addItem("")
        self.signalOffsetCombo.addItem("")
        self.signalOffsetCombo.addItem("")
        self.signalOffsetCombo.setObjectName(u"signalOffsetCombo")

        self.gridLayout.addWidget(self.signalOffsetCombo, 0, 1, 1, 1)

        self.signalOffsetParamsEdit = QLineEdit(self.bgCorrectionGroupBox)
        self.signalOffsetParamsEdit.setObjectName(u"signalOffsetParamsEdit")

        self.gridLayout.addWidget(self.signalOffsetParamsEdit, 0, 2, 1, 1)

        self.refOffsetCombo = QComboBox(self.bgCorrectionGroupBox)
        self.refOffsetCombo.addItem("")
        self.refOffsetCombo.addItem("")
        self.refOffsetCombo.addItem("")
        self.refOffsetCombo.addItem("")
        self.refOffsetCombo.setObjectName(u"refOffsetCombo")

        self.gridLayout.addWidget(self.refOffsetCombo, 1, 1, 1, 1)

        self.refOffsetParamsEdit = QLineEdit(self.bgCorrectionGroupBox)
        self.refOffsetParamsEdit.setObjectName(u"refOffsetParamsEdit")

        self.gridLayout.addWidget(self.refOffsetParamsEdit, 1, 2, 1, 1)

        self.label_5 = QLabel(self.bgCorrectionGroupBox)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout.addWidget(self.label_5, 0, 0, 1, 1)

        self.label_6 = QLabel(self.bgCorrectionGroupBox)
        self.label_6.setObjectName(u"label_6")

        self.gridLayout.addWidget(self.label_6, 1, 0, 1, 1)

        self.horizontalSpacer_3 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.gridLayout.addItem(self.horizontalSpacer_3, 2, 0, 1, 1)

        self.applyToSetButton = QPushButton(self.bgCorrectionGroupBox)
        self.applyToSetButton.setObjectName(u"applyToSetButton")

        self.gridLayout.addWidget(self.applyToSetButton, 2, 1, 1, 1)

        self.applyToAllButton = QPushButton(self.bgCorrectionGroupBox)
        self.applyToAllButton.setObjectName(u"applyToAllButton")

        self.gridLayout.addWidget(self.applyToAllButton, 2, 2, 1, 1)


        self.verticalLayout_3.addWidget(self.bgCorrectionGroupBox)

        self.splitter.addWidget(self.rightPanelWidget)

        self.verticalLayout_2.addWidget(self.splitter)


        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.label.setText(QCoreApplication.translate("Form", u"Up-conversion wavelength:", None))
        self.upconversionSpinBox.setSuffix(QCoreApplication.translate("Form", u" nm", None))
        self.calibrateButton.setText(QCoreApplication.translate("Form", u"\u25b6 Calibrate with polystyrene...", None))
        self.reviewReferencesButton.setText(QCoreApplication.translate("Form", u"Review references", None))
        self.label_2.setText(QCoreApplication.translate("Form", u"Matched Sets", None))
        self.setStatusLabel.setText("")
        self.label_3.setText(QCoreApplication.translate("Form", u"View:", None))
        self.singleViewRadio.setText(QCoreApplication.translate("Form", u"Single", None))
        self.compareViewRadio.setText(QCoreApplication.translate("Form", u"Compare", None))
        self.label_4.setText(QCoreApplication.translate("Form", u"Step:", None))
        self.rawStepRadio.setText(QCoreApplication.translate("Form", u"Raw", None))
        self.despikedStepRadio.setText(QCoreApplication.translate("Form", u"Despiked", None))
        self.averagedStepRadio.setText(QCoreApplication.translate("Form", u"Averaged", None))
        self.bgSubtractedStepRadio.setText(QCoreApplication.translate("Form", u"BG Subtracted", None))
        self.normalizedStepRadio.setText(QCoreApplication.translate("Form", u"Normalized", None))
        self.processAllButton.setText(QCoreApplication.translate("Form", u"\u25b6 Process All", None))
        self.bgCorrectionGroupBox.setTitle(QCoreApplication.translate("Form", u"Background Correction", None))
        self.signalOffsetCombo.setItemText(0, QCoreApplication.translate("Form", u"None", None))
        self.signalOffsetCombo.setItemText(1, QCoreApplication.translate("Form", u"Constant", None))
        self.signalOffsetCombo.setItemText(2, QCoreApplication.translate("Form", u"Linear", None))
        self.signalOffsetCombo.setItemText(3, QCoreApplication.translate("Form", u"Polynomial", None))

        self.signalOffsetParamsEdit.setText(QCoreApplication.translate("Form", u"0", None))
        self.refOffsetCombo.setItemText(0, QCoreApplication.translate("Form", u"None", None))
        self.refOffsetCombo.setItemText(1, QCoreApplication.translate("Form", u"Constant", None))
        self.refOffsetCombo.setItemText(2, QCoreApplication.translate("Form", u"Linear", None))
        self.refOffsetCombo.setItemText(3, QCoreApplication.translate("Form", u"Polynomial", None))

        self.refOffsetParamsEdit.setText(QCoreApplication.translate("Form", u"0", None))
        self.label_5.setText(QCoreApplication.translate("Form", u"Signal BG offset:", None))
        self.label_6.setText(QCoreApplication.translate("Form", u"Ref BG offset:", None))
        self.applyToSetButton.setText(QCoreApplication.translate("Form", u"Apply to set", None))
        self.applyToAllButton.setText(QCoreApplication.translate("Form", u"Apply to all", None))
    # retranslateUi

