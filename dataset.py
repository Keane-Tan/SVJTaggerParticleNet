import numpy as np
import uproot as up
from magiconfig import ArgumentParser, MagiConfigOptions, ArgumentDefaultsRawHelpFormatter
from configs import configs as c
import torch.utils.data as udata
import torch
import pandas as pd
from tqdm import tqdm

def getParticleNetInputs(dataSet,signalFileIndex,numConst):
    varSet = dataSet.columns.tolist()
    data = dataSet.to_numpy()
    evtNumIndex = varSet.index("jCstEvtNum")
    fJetNumIndex = varSet.index("jCstJNum")
    etaIndex = varSet.index("jCstEta")
    phiIndex = varSet.index("jCstPhi")
    inFileIndex = varSet.index("inputFile")
    hvIndex = varSet.index("jCsthvCategory")
    jIDIndex = varSet.index("jID")
    evtNumColumn = data[:,evtNumIndex]
    fJetNumColumn = data[:,fJetNumIndex]
    inFileColumn = data[:,inFileIndex]
    inFColumn = data[:,inFileIndex]
    jIDColumn = data[:,jIDIndex]

    inputPoints = []
    inputFeatures = []
    inputFileIndices = []
    # grouping constituents that belong to the same jet together
    print("There are {} unique jets.".format(len(np.unique(jIDColumn))))
    count = 1
    signal = []
    for jID in np.unique(jIDColumn):
        if count % 200 == 0:
            print("Transformed {} jets".format(count))
        count += 1
        sameJetConstData = data[jIDColumn == jID] # getting values for constituents in the same jet
        if sameJetConstData[0][inFileIndex] in signalFileIndex:
            signal.append([0, 1])
        else:
            signal.append([1, 0])
        sameJetConstDataTr = np.transpose(sameJetConstData)
        if numConst > sameJetConstDataTr.shape[1]:
            paddedJetConstData = np.pad(sameJetConstDataTr,((0,0),(0,numConst-sameJetConstDataTr.shape[1])), 'constant', constant_values=0)
        else:
            paddedJetConstData = sameJetConstDataTr[:,:numConst]
        eachJetPoints = np.array([paddedJetConstData[etaIndex],paddedJetConstData[phiIndex]])
        eachJetFeatures = []
        for i in range(paddedJetConstData.shape[0]):
            # make sure information that would easily give away the identity of the jet is not included as input features
            if i not in [etaIndex,phiIndex,evtNumIndex,fJetNumIndex,inFileIndex,hvIndex,jIDIndex]:
                eachJetFeatures.append(paddedJetConstData[i])
        inputPoints.append(eachJetPoints)
        inputFeatures.append(eachJetFeatures)
        inputFileIndices.append(inFileColumn[jIDColumn == jID][0])
    inputPoints = np.array(inputPoints)
    inputFeatures = np.array(inputFeatures)
    print("There are {} labels.".format(len(signal)))
    print(inputPoints.shape)
    print(inputFeatures.shape)
    return inputPoints, inputFeatures, signal, inputFileIndices

def getBranch(ftree,variable,branches,branchList):
    branch = ftree.arrays(variable,library="pd")
    branch = branch.head(len(branches))
    branchList.append(branch)

def getPara(fileName,paraName,paraList,branches,key):
    paravalue = 0
    if key == "signal":
        ind = fileName.find(paraName)
        fnCut = fileName[ind:]
        indUnd = fnCut.find("_")
        paravalue = fnCut[len(paraName)+1:indUnd]
        if paraName == "alpha":
            if paravalue == "low":
                paravalue = 1
            elif paravalue == "peak":
                paravalue = 2
            elif paravalue == "high":
                paravalue = 3
        else:
            paravalue = float(paravalue)
    paraList += [paravalue]*len(branches)

def normalize(df):
    return (df-df.mean())/df.std()

def jetIdentifier(dataSet):
    dataSet["jID"] = (dataSet["jCstEvtNum"].astype(int))*10**6 + (dataSet["inputFile"].astype(int))*1000 + dataSet["jCstJNum"].astype(int)

def get_all_vars(inputFolder, samples, variables, pTBins, uniform, mT, weight, numConst, tree="tree"):
    dSets = []
    signal = []
    mcType =[] # 0 = signals other than baseline, 1 = baseline signal, 2 = QCD, 3 = TTJets
    pTLab = np.array([])
    pTs = []
    mTs = []
    mMeds = []
    mDarks = []
    rinvs = []
    alphas = []
    weights = []
    fileIndex = 0
    signalFileIndex = []
    for key,fileList in samples.items():
        nsigfiles = len(samples["signal"])
        nbkgfiles = len(samples["background"])
        for fileName in fileList:
            print(fileName)
            f = up.open(inputFolder  + fileName + ".root")
            ftree = f[tree]
            branches = ftree.arrays(variables,library="pd")
            if key == "signal":
                signalFileIndex.append(fileIndex)
                jetCatBranch = ftree.arrays("jCsthvCategory",library="pd")
                darkCon = ((jetCatBranch["jCsthvCategory"] == 3) | (jetCatBranch["jCsthvCategory"] == 5) | (jetCatBranch["jCsthvCategory"] == 9))
                # print(jetCatBranch['jCsthvCategory'].value_counts())
                branches = branches[darkCon]
            branches["inputFile"] = [fileIndex]*len(branches) # record name of the input file, important for distinguishing which jet the constituents belong to
            fileIndex += 1
            branches.replace([np.inf, -np.inf], np.nan, inplace=True)
            branches = branches.dropna()
            numEvent = len(branches)
            minNum = 105238 # 105238
            maxMultiple = 1
            maxNum = minNum * maxMultiple # using 105238 for lowest number of constituents from the training
            # if we do not limit the number of constituents we read in, the code is gonna take very long to run
            if numEvent > maxNum:
                numEvent = maxNum
            elif minNum < numEvent < maxNum:
                factor = numEvent//minNum
                numEvent = factor*minNum # make sure the number of constituents we keep are multiples of the minNum
            branches = branches.head(numEvent)
            print("Total Number of constituents for {}".format(fileName))
            print(len(branches))
            # print(len(branches))
            # branches = branches.head(10000)
            dSets.append(branches)
            getBranch(ftree,uniform,branches,pTs)
            getBranch(ftree,mT,branches,mTs)
            getBranch(ftree,weight,branches,weights)
            # getPara(fileName,"mZprime",mMeds,branches,key)
            getPara(fileName,"mMed",mMeds,branches,key) # use this for t-channel
            getPara(fileName,"mDark",mDarks,branches,key)
            getPara(fileName,"rinv",rinvs,branches,key)
            getPara(fileName,"alpha",alphas,branches,key)
            # get the pT label based on what pT bin the jet pT falls into
            branch = ftree.arrays(uniform,library="pd")
            branch = branch.head(len(branches)).to_numpy().flatten()
            pTLabel = np.digitize(branch,pTBins) - 1.0
            pTLab = np.append(pTLab,pTLabel)
            if key == "signal":
                signal += list([0, 1] for _ in range(len(branches)))
                if fileName == "tree_SVJ_mZprime-3000_mDark-20_rinv-0.3_alpha-peak_MC2017":
                    mcType += [1] * len(branches)
                else:
                    mcType += [0] * len(branches)
            else:
                signal += list([1, 0] for _ in range(len(branches)))
                if "QCD" in fileName:
                    mcType += [2] * len(branches)
                else:
                    mcType += [3] * len(branches)
            print("Number of Constituents",len(branches))
    mcType = np.array(mcType)
    mMed = np.array(mMeds)
    mDark = np.array(mDarks)
    rinv = np.array(rinvs)
    alpha = np.array(alphas)
    dataSet = pd.concat(dSets)
    jetIdentifier(dataSet)
    print("dataSet.head()")
    print(dataSet.head())
    print("The number of constituents in each input training file:")
    print(dataSet["inputFile"].value_counts())
    dfmean = dataSet.mean()
    dfstd = dataSet.std()
    dataSet["jCstEta_Norm"] = dataSet["jCstEta"]
    dataSet["jCstPhi_Norm"] = dataSet["jCstPhi"]
    columns_to_normalize = [var for var in variables if var not in ["jCstEta","jCstPhi","inputFile","jCstEvtNum","jCstJNum"]]
    dataSet[columns_to_normalize] = normalize(dataSet[columns_to_normalize])
    pT = pd.concat(pTs)
    mT = pd.concat(mTs)
    weight = pd.concat(weights)
    inputPoints, inputFeatures, signal, inputFileIndices = getParticleNetInputs(dataSet,signalFileIndex,numConst)
    sigLabel = np.array(signal)[:,1]
    print("The total number of jets: {}".format(len(sigLabel)))
    print("Total number of signal jets: {}".format(len(sigLabel[sigLabel==1])))
    print("Total number of background jets: {}".format(len(sigLabel[sigLabel==0])))
    return [inputPoints,inputFeatures,signal,mcType,pTLab,pT,mT,weight,mMed,mDark,rinv,alpha,dfmean,dfstd,inputFileIndices,signalFileIndex]

def splitArrayByChunkSize(alist,chunkSize):
    if chunkSize > len(alist):
        chunkSize = len(alist)
    numOfChunks = len(alist) // chunkSize
    aListChunks = []
    start = 0
    for i in range(numOfChunks):
        end = start + chunkSize
        aListChunks.append(alist[start:end])
        start = end
    return aListChunks

def splitDataSetEvenly(dataset,rng,numOfEpoch=10):
    inputFileIndex = dataset.inputFileIndex
    signalFileIndex = dataset.signalFileIndex
    listIndices = np.arange(len(inputFileIndex))
    inputFileIndex = np.array(inputFileIndex)
    minOcc = np.amin(np.unique(inputFileIndex,return_counts=True)[1])
    uniqueFileIndices = np.unique(inputFileIndex)
    numOfSigFiles = len(signalFileIndex)
    numOfBkgFiles = len(uniqueFileIndices) - numOfSigFiles
    allSamplesIndices = []
    numOfSets = []
    for i in uniqueFileIndices:
        chunkSize = minOcc
        subIndexList = listIndices[inputFileIndex==i]
        rng.shuffle(subIndexList)
        if i not in signalFileIndex:
            chunkSize = int(minOcc*(numOfSigFiles/numOfBkgFiles)) # this is assuming there are more background events than signal events in general
        indexSet = splitArrayByChunkSize(subIndexList,chunkSize)
        allSamplesIndices.append(indexSet)
        numOfSets.append(len(indexSet))
    randBalancedSet = []
    for i in range(numOfEpoch):
        randomIndexSet = [rng.randint(0,high=ind) for ind in numOfSets]
        indicesForEpoch = np.array([],dtype=int)
        for j in range(len(allSamplesIndices)):
            indicesForEpoch = np.concatenate((indicesForEpoch,allSamplesIndices[j][randomIndexSet[j]]))
        randBalancedSet.append(indicesForEpoch)
    return randBalancedSet

def get_sizes(l, frac=[0.8, 0.1, 0.1]):
    if sum(frac) != 1.0: raise ValueError("Sum of fractions does not equal 1.0")
    if len(frac) != 3: raise ValueError("Need three numbers in list for train, test, and val respectively")
    train_size = int(frac[0]*l)
    test_size = int(frac[1]*l)
    val_size = l - train_size - test_size
    return [train_size, test_size, val_size]

class RootDataset(udata.Dataset):
    def __init__(self, inputFolder, root_file, variables, pTBins, uniform, mT, weight, numConst):
        inputPoints, inputFeatures, signal, mcType, pTLab, pTs, mTs, weights, mMeds, mDarks, rinvs, alphas, dfmean, dfstd, inputFileIndex, signalFileIndex = get_all_vars(inputFolder, root_file, variables, pTBins, uniform, mT, weight, numConst)
        self.root_file = root_file
        self.variables = variables
        self.uniform = uniform
        self.weight = weight
        # self.vars = dataSet.astype(float).values
        self.points = inputPoints
        self.features = inputFeatures
        self.signal = signal
        self.mcType = mcType
        self.pTLab = pTLab
        self.pTs = pTs.astype(float).values
        self.mTs = mTs.astype(float).values
        self.weights = weights.astype(float).values
        self.mMeds = mMeds
        self.mDarks = mDarks
        self.rinvs = rinvs
        self.alphas = alphas
        self.normMean = np.array(dfmean)
        self.normstd = np.array(dfstd)
        self.inputFileIndex = np.array(inputFileIndex)
        self.signalFileIndex = np.array(signalFileIndex)
        print("Number of events:", len(self.signal))

    #def get_arrays(self):
    #    return np.array(self.signal), torch.from_numpy(self.vars.astype(float).values.copy()).float().squeeze(1)

    def __len__(self):
        return len(self.points)

    def __getitem__(self, idx):
        points_np = self.points[idx].copy()
        features_np = self.features[idx].copy()
        label_np = np.zeros(1, dtype=np.long).copy()
        mcType_np = np.array([np.long(self.mcType[idx])]).copy()
        pTLab_np = np.array([np.long(self.pTLab[idx])]).copy()
        pTs_np = self.pTs[idx].copy()
        mTs_np = self.mTs[idx].copy()
        weights_np = self.weights[idx].copy()
        mMeds_np = np.array([self.mMeds[idx]]).copy()
        mDarks_np = np.array([self.mDarks[idx]]).copy()
        rinvs_np = np.array([self.rinvs[idx]]).copy()
        alphas_np = np.array([np.long(self.alphas[idx])]).copy()

        if self.signal[idx][1]:
            label_np += 1

        points  = torch.from_numpy(points_np)
        features  = torch.from_numpy(features_np)
        # print("Data inside getitem")
        # print(data)
        label = torch.from_numpy(label_np)
        mcType = torch.from_numpy(mcType_np)
        pTLab = torch.from_numpy(pTLab_np)
        pTs = torch.from_numpy(pTs_np).float()
        mTs = torch.from_numpy(mTs_np).float()
        weights = torch.from_numpy(weights_np).float()
        mMeds = torch.from_numpy(mMeds_np).float()
        mDarks = torch.from_numpy(mDarks_np).float()
        rinvs = torch.from_numpy(rinvs_np).float()
        alphas = torch.from_numpy(alphas_np)
        return label, points, features, mcType, pTLab, pTs, mTs, weights, mMeds, mDarks, rinvs, alphas

if __name__=="__main__":
    # parse arguments
    rng = np.random.RandomState(2022) # set seeds for numpy.random
    parser = ArgumentParser(config_options=MagiConfigOptions(strict = True, default="configs/C1.py"),formatter_class=ArgumentDefaultsRawHelpFormatter)
    parser.add_config_only(*c.config_schema)
    parser.add_config_only(**c.config_defaults)
    args = parser.parse_args()
    dSet = args.dataset
    sigFiles = dSet.signal
    inputFiles = dSet.background
    inputFiles.update(sigFiles)
    print(inputFiles)
    varSet = args.features.train
    print(varSet)
    pTBins = args.hyper.pTBins
    print(pTBins)
    uniform = args.features.uniform
    mTs = args.features.mT
    weights = args.features.weight
    numConst = args.hyper.numConst
    dataset = RootDataset(dSet.path, inputFiles, varSet, pTBins, uniform, mTs, weights, numConst)
    print("Splitting dataset")
    # print(udata.Subset(dataset,np.arange(0,100)))
    randBalancedSet = splitDataSetEvenly(dataset)
    entireDataSet = dataset
    print("randBalancedSet:")
    for set in randBalancedSet:
        print(set)
    for i in range(10):
        dataset = udata.Subset(entireDataSet,randBalancedSet[i])
        sizes = get_sizes(len(dataset), dSet.sample_fractions)
        train, val, test = udata.random_split(dataset, sizes, generator=torch.Generator().manual_seed(42))
        loader = udata.DataLoader(dataset=train, batch_size=train.__len__(), num_workers=0)
        l, po, fea, mct, pl, p, m, w, med, dark, rinv, alpha = next(iter(loader))
    labels = l.squeeze(1).numpy()
    mcType = mct.squeeze(1).numpy()
    pTLab = pl.squeeze(1).numpy()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    points = po.float().numpy()
    trainPoints = po.float().to(device)
    features = fea.float().numpy()
    trainFeatures = fea.float().to(device)
    pTs = p.squeeze(1).float().numpy()
    mTs = m.squeeze(1).float().numpy()
    weights = w.squeeze(1).float().numpy()
    meds = med.squeeze(1).float().numpy()
    darks = dark.squeeze(1).float().numpy()
    rinvs = rinv.squeeze(1).float().numpy()
    alphas = alpha.squeeze(1).numpy()
    print("labels:", labels)
    print("Number of signals: ",len(labels[labels==1]))
    print("Number of backgrounds: ",len(labels[labels==0]))
    print("Information for Points:")
    print("Input has nan:",np.isnan(np.sum(points)))
    print("inputMean:", np.mean(points,axis=0))
    print("inputSTD:", np.std(points,axis=0))
    print("Information for Features:")
    print("Input has nan:",np.isnan(np.sum(features)))
    print("inputMean:", np.mean(features,axis=0))
    print("inputSTD:", np.std(features,axis=0))
    print("mcType:", mcType)
    print("pTLab:", pTLab)
    print("mT:", mTs)
    print("pT:", pTs)
    print("weights", weights)
    print("meds:", np.unique(meds))
    print("darks:", np.unique(darks))
    print("rinvs:", np.unique(rinvs))
    print("alphas", np.unique(alphas))
