# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'load_match_tab.ui'
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QHeaderView,
    QListView, QPushButton, QSizePolicy, QSpacerItem,
    QSplitter, QTableView, QVBoxLayout, QWidget)

class Ui_loadmatchTab(object):
    def setupUi(self, loadmatchTab):
        if not loadmatchTab.objectName():
            loadmatchTab.setObjectName(u"loadmatchTab")
        loadmatchTab.resize(805, 539)
        self.verticalLayout = QVBoxLayout(loadmatchTab)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.splitter = QSplitter(loadmatchTab)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.loadedfilesListView = QListView(self.splitter)
        self.loadedfilesListView.setObjectName(u"loadedfilesListView")
        self.loadedfilesListView.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.splitter.addWidget(self.loadedfilesListView)
        self.matchedfilesTableView = QTableView(self.splitter)
        self.matchedfilesTableView.setObjectName(u"matchedfilesTableView")
        self.splitter.addWidget(self.matchedfilesTableView)

        self.verticalLayout.addWidget(self.splitter)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.pushButton = QPushButton(loadmatchTab)
        self.pushButton.setObjectName(u"pushButton")

        self.horizontalLayout.addWidget(self.pushButton)

        self.automatchButton = QPushButton(loadmatchTab)
        self.automatchButton.setObjectName(u"automatchButton")

        self.horizontalLayout.addWidget(self.automatchButton)

        self.horizontalSpacer = QSpacerItem(40, 25, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.startprocessingButton = QPushButton(loadmatchTab)
        self.startprocessingButton.setObjectName(u"startprocessingButton")

        self.horizontalLayout.addWidget(self.startprocessingButton)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.verticalLayout.setStretch(0, 1)

        self.retranslateUi(loadmatchTab)

        QMetaObject.connectSlotsByName(loadmatchTab)
    # setupUi

    def retranslateUi(self, loadmatchTab):
        loadmatchTab.setWindowTitle(QCoreApplication.translate("loadmatchTab", u"Form", None))
        self.pushButton.setText(QCoreApplication.translate("loadmatchTab", u"Update", None))
        self.automatchButton.setText(QCoreApplication.translate("loadmatchTab", u"Auto-match Files", None))
        self.startprocessingButton.setText(QCoreApplication.translate("loadmatchTab", u"Start Processing", None))
    # retranslateUi

