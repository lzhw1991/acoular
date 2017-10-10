#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
This file contains all the functionalities which are very expansive, regarding
computational costs. All functionalities are optimized via NUMBA.
"""
import numpy as np
import numba as nb

cachedOption = True  # if True: saves the numba func as compiled func in sub directory
parallelOption = 'parallel'  # if numba.guvectorize is used: 'CPU' for single threading; 'parallel' for multithreading; 'cuda' for calculating on GPU


# Formerly known as 'faverage'
@nb.njit(nb.complex128[:,:,:](nb.complex128[:,:,:], nb.complex128[:,:]), cache=cachedOption)
def calcCSM(csm, SpecAllMics):
    """ Adds a given spectrum to the Cross-Spectral-Matrix (CSM).
    Here only the upper triangular matrix of the CSM is calculated. After
    averaging over the various ensembles, the whole CSM is created via complex 
    conjugation transposing. This happens outside (in acoular.spectra). This method
    was called 'faverage' in earlier versions of acoular.
    
    Input
    -----
        ``csm`` ... complex128[nFreqs, nMics, nMics] --> the current CSM.
        
        ``SpecAllMics`` ...complex128[nFreqs, nMics] --> spectrum of the added ensemble at all Mics.
    
    Returns
    -------
        ``None`` ... as the input ``csm`` gets overwritten.
    """
#==============================================================================
#     It showed, that parallelizing brings no benefit when calling calcCSM once per 
#     ensemble (as its done at the moment). BUT it could be whorth, taking a closer 
#     look to parallelization, when averaging over all ensembles inside this numba 
#     optimized function. See "vglOptimierungFAverage.py" for some information on 
#     the various implementations and their limitations.
#==============================================================================
    nFreqs = csm.shape[0]
    nMics = csm.shape[1]
    for cntFreq in range(nFreqs):
        for cntColumn in range(nMics):
            temp = SpecAllMics[cntFreq, cntColumn].conjugate()
            for cntRow in range(cntColumn + 1):  # calculate upper triangular matrix (of every frequency-slice) only
                csm[cntFreq, cntRow, cntColumn] += temp * SpecAllMics[cntFreq, cntRow]
    return csm

    
def beamformerFreq(boolIsEigValProb, steerVecType, boolRemovedDiagOfCSM, normFactor, inputTuple):
    """ Conventional beamformer in frequency domain. Use either a predefined
    steering vector formulation (see Sarradj 2012) or pass it your own
    steering vector.

    Input
    -----
        ``boolIsEigValProb`` (bool) ... should the beamformer use spectral
        decomposition of the csm matrix?

        ``steerVecType`` (one of the following options: 1, 2, 3, 4, 'specific') ...
        either build the steering vector via the predefined formulations
        I - IV (see Sarradj 2012) or pass it directly.

        ``boolRemovedDiagOfCSM`` (bool) ... should the diagonal of the csm be removed?
        
        ``normFactor`` (float) ... in here both the signalenergy loss factor (due to removal of the csm diagonal) as well as
        beamforming algorithm (functional, capon, ...) dependent normalization factors are handled.

        ``inputTuple`` ... dependent of the inputs above. If

                    ``boolIsEigValProb`` = False & ``steerVecType`` != 'specific' --> ``inputTuple`` =( ``distGridToArrayCenter``, ``distGridToAllMics``, ``wavenumber``, ``csm``)

                    ``boolIsEigValProb`` = False & ``steerVecType`` = 'specific'  --> ``inputTuple`` =( ``steeringVector``, ``csm``)

                    ``boolIsEigValProb`` = True  & ``steerVecType`` != 'specific' --> ``inputTuple`` =( ``distGridToArrayCenter``, ``distGridToAllMics``, ``wavenumber``, ``eigValues``, ``eigVectors``)

                    ``boolIsEigValProb`` = True  & ``steerVecType`` = 'specific'  --> ``inputTuple`` =( ``steeringVector``, ``eigValues``, ``eigVectors``)


                    In all 4 cases:

                        ``distGridToArrayCenter`` ... float64[nGridpoints]

                        ``distGridToAllMics`` ... float64[nGridpoints, nMics]

                        ``wavenumber`` ... complex128[nFreqs] (the wavenumber should be stored in the imag-part)

                        ``csm`` ... complex128[nFreqs, nMics, nMics]

                        ``steeringVector`` ... complex128[nFreqs, nGridPoints, nMics]

                        ``eigValues`` ... float64[nFreqs, nEV] (nEV ... number of eigenvalues which should be taken into account. The chosen eigenvalues have to be passed to 'beamformerFreq'.)

                        ``eigVectors`` ... complex128[nFreqs, nMics, nEV] (eigenvectors corresponding to ``eigVectors``)

    Returns
    -------
        Autopower spectrum beamforming map [nFreqs, nGridPoints]
    
    Some Notes on the optimization of all subroutines
    -------------------------------------------------
        Reducing beamforming equation:
            Let the csm be C and the steering vector be h, than, using Linear Albegra, the conventional beamformer can be written as 
            
            .. math:: B = h^H \\cdot C \\cdot h,
            with ^H meaning the complex conjugated transpose.
            When using that C is a hermitian matrix one can reduce the equation to
            
            .. math:: B = h^H \\cdot C_D \\cdot h + 2 \\cdot Real(h^H \\cdot C_U \\cdot h),
            where C_D and C_U are the diagonal part and upper part of C respectively.
        Steering vector:
            Theoretically the steering vector always includes the term "exp(distMicsGrid - distArrayCenterGrid)", but as the steering vector gets multplied with its complex conjugation in 
            all beamformer routines, the constant "distArrayCenterGrid" cancels out --> In order to save operations, it is not implemented.
        Spectral decomposition of the CSM:
            In Linear Algebra the spectral decomposition of the CSM matrix would be:
            
            .. math:: CSM = \\sum_{i=1}^{nEigenvalues} \\lambda_i (v_i \\cdot v_i^H) ,
            where lambda_i is the i-th eigenvalue and 
            v_i is the eigenvector[nEigVal,1] belonging to lambda_i and ^H denotes the complex conjug transpose. Using this, one must not build the whole CSM 
            (which would be time consuming), but can drag the steering vector into the sum of the spectral decomp. This saves a lot of operations.
        Squares:
            Seemingly "a * a" is slightly faster than "a**2" in numba
        Square of abs():
            Even though "a.real**2 + a.imag**2" would have fewer operations, modern processors seem to be optimized for "a * a.conj" and are slightly faster the latter way.
            Both Versions are much faster than "abs(a)**2".
        Using Cascading Sums:
            When using the Spectral-Decomposition-Beamformer one could use numpys cascading sums for the scalar product "eigenVec.conj * steeringVector". BUT (at the moment) this only brings benefits 
            in comp-time for a very small range of nMics (approx 250) --> Therefor it is not implemented here.
    """
    # get the beamformer type (key-tuple = (isEigValProblem, formulationOfSteeringVector, RemovalOfCSMDiag))
    beamformerDict = {(False, 1, False) : _freqBeamformer_Formulation1AkaClassic_FullCSM,
                      (False, 1, True) : _freqBeamformer_Formulation1AkaClassic_CsmRemovedDiag,
                      (False, 2, False) : _freqBeamformer_Formulation2AkaInverse_FullCSM,
                      (False, 2, True) : _freqBeamformer_Formulation2AkaInverse_CsmRemovedDiag,
                      (False, 3, False) : _freqBeamformer_Formulation3AkaTrueLevel_FullCSM,
                      (False, 3, True) : _freqBeamformer_Formulation3AkaTrueLevel_CsmRemovedDiag,
                      (False, 4, False) : _freqBeamformer_Formulation4AkaTrueLocation_FullCSM,
                      (False, 4, True) : _freqBeamformer_Formulation4AkaTrueLocation_CsmRemovedDiag,
                      (False, 'specific', False) : _freqBeamformer_SpecificSteerVec_FullCSM,
                      (False, 'specific', True) : _freqBeamformer_SpecificSteerVec_CsmRemovedDiag,
                      (True, 1, False) : _freqBeamformer_EigValProb_Formulation1AkaClassic_FullCSM,
                      (True, 1, True) : _freqBeamformer_EigValProb_Formulation1AkaClassic_CsmRemovedDiag,
                      (True, 2, False) : _freqBeamformer_EigValProb_Formulation2AkaInverse_FullCSM,
                      (True, 2, True) : _freqBeamformer_EigValProb_Formulation2AkaInverse_CsmRemovedDiag,
                      (True, 3, False) : _freqBeamformer_EigValProb_Formulation3AkaTrueLevel_FullCSM,
                      (True, 3, True) : _freqBeamformer_EigValProb_Formulation3AkaTrueLevel_CsmRemovedDiag,
                      (True, 4, False) : _freqBeamformer_EigValProb_Formulation4AkaTrueLocation_FullCSM,
                      (True, 4, True) : _freqBeamformer_EigValProb_Formulation4AkaTrueLocation_CsmRemovedDiag,
                      (True, 'specific', False) : _freqBeamformer_EigValProb_SpecificSteerVec_FullCSM,
                      (True, 'specific', True) : _freqBeamformer_EigValProb_SpecificSteerVec_CsmRemovedDiag,}
    coreFunc = beamformerDict[(boolIsEigValProb, steerVecType, boolRemovedDiagOfCSM)]

    # prepare Input
    if steerVecType == 'specific':  # beamformer with specific steering vector
        steerVec = inputTuple[0]
        nFreqs, nGridPoints = steerVec.shape[0], steerVec.shape[1]
        if boolIsEigValProb:
            eigVal, eigVec = inputTuple[1], inputTuple[2]
        else:
            csm = inputTuple[1]
    else:  # predefined beamformers (Formulation I - IV)
        distGridToArrayCenter, distGridToAllMics, wavenumber = inputTuple[0], inputTuple[1], inputTuple[2]
        nFreqs, nGridPoints = wavenumber.shape[0], distGridToAllMics.shape[0]
        if boolIsEigValProb:
            eigVal, eigVec = inputTuple[3], inputTuple[4]
        else:
            csm = inputTuple[3]
    
    # beamformer routine: parallelized over Gridpoints
    beamformOutput = np.zeros((nFreqs, nGridPoints), np.float64)
    for cntFreqs in xrange(nFreqs):
        result = np.zeros(nGridPoints, np.float64)
        if steerVecType == 'specific':  # beamformer with specific steering vector
            if boolIsEigValProb:
                coreFunc(eigVal[cntFreqs, :], eigVec[cntFreqs, :, :], steerVec[cntFreqs, :, :], normFactor, result)
            else:
                coreFunc(csm[cntFreqs, :, :], steerVec[cntFreqs, :, :], normFactor, result)
        else:  # predefined beamformers (Formulation I - IV)
            if boolIsEigValProb:
                coreFunc(eigVal[cntFreqs, :], eigVec[cntFreqs, :, :], distGridToArrayCenter, distGridToAllMics, wavenumber[cntFreqs].imag, normFactor, result)
            else:
                coreFunc(csm[cntFreqs, :, :], distGridToArrayCenter, distGridToAllMics, wavenumber[cntFreqs].imag, normFactor, result)
        beamformOutput[cntFreqs, :] = result
    return beamformOutput


#%% beamformers - steer * CSM * steer
@nb.guvectorize([(nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(m,m),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_Formulation1AkaClassic_FullCSM(csm, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * distGridToAllMics[cntMics])
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg))

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq)
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
        scalarProd += (csm[cntMics, cntMics] * steerVec[cntMics].conjugate() * steerVec[cntMics]).real  # include diagonal of csm
    normalizeFactor = nMics  # specific normalization of steering vector formulation
    result[0] = scalarProd / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(m,m),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_Formulation1AkaClassic_CsmRemovedDiag(csm, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * distGridToAllMics[cntMics])
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg))

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
    normalizeFactor = nMics  # specific normalization of steering vector formulation
    result[0] = scalarProd / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(m,m),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_Formulation2AkaInverse_FullCSM(csm, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * distGridToAllMics[cntMics])
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) * distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
        scalarProd += (csm[cntMics, cntMics] * steerVec[cntMics].conjugate() * steerVec[cntMics]).real  # include diagonal of csm
    normalizeFactor = nMics * distGridToArrayCenter[0]  # specific normalization of steering vector formulation
    result[0] = scalarProd / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(m,m),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_Formulation2AkaInverse_CsmRemovedDiag(csm, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * distGridToAllMics[cntMics])
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) * distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
    normalizeFactor = nMics * distGridToArrayCenter[0]  # specific normalization of steering vector formulation
    result[0] = scalarProd / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(m,m),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_Formulation3AkaTrueLevel_FullCSM(csm, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    helpNormalize = 0.0
    for cntMics in xrange(nMics):
        helpNormalize += 1.0 / (distGridToAllMics[cntMics] * distGridToAllMics[cntMics])  
        expArg = np.float32(waveNumber[0] * distGridToAllMics[cntMics])
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) / distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
        scalarProd += (csm[cntMics, cntMics] * steerVec[cntMics].conjugate() * steerVec[cntMics]).real  # include diagonal of csm
    normalizeFactor = distGridToArrayCenter[0] * helpNormalize  # specific normalization of steering vector formulation
    result[0] = scalarProd / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(m,m),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_Formulation3AkaTrueLevel_CsmRemovedDiag(csm, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    helpNormalize = 0.0
    for cntMics in xrange(nMics):
        helpNormalize += 1.0 / (distGridToAllMics[cntMics] * distGridToAllMics[cntMics])  
        expArg = np.float32(waveNumber[0] * distGridToAllMics[cntMics])
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) / distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
    normalizeFactor = distGridToArrayCenter[0] * helpNormalize  # specific normalization of steering vector formulation
    result[0] = scalarProd / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(m,m),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_Formulation4AkaTrueLocation_FullCSM(csm, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    helpNormalize = 0.0
    for cntMics in xrange(nMics):
        helpNormalize += 1.0 / (distGridToAllMics[cntMics] * distGridToAllMics[cntMics])  
        expArg = np.float32(waveNumber[0] * distGridToAllMics[cntMics])
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) / distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
        scalarProd += (csm[cntMics, cntMics] * steerVec[cntMics].conjugate() * steerVec[cntMics]).real  # include diagonal of csm
    normalizeFactor = nMics * helpNormalize  # specific normalization of steering vector formulation
    result[0] = scalarProd / normalizeFactor * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(m,m),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_Formulation4AkaTrueLocation_CsmRemovedDiag(csm, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    helpNormalize = 0.0
    for cntMics in xrange(nMics):
        helpNormalize += 1.0 / (distGridToAllMics[cntMics] * distGridToAllMics[cntMics])  
        expArg = np.float32(waveNumber[0] * distGridToAllMics[cntMics])
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) / distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
    normalizeFactor = nMics * helpNormalize  # specific normalization of steering vector formulation
    result[0] = scalarProd / normalizeFactor * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.complex128[:], nb.float64[:], nb.float64[:])], '(m,m),(m),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_SpecificSteerVec_FullCSM(csm, steerVec, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
        scalarProd += (csm[cntMics, cntMics] * steerVec[cntMics].conjugate() * steerVec[cntMics]).real  # include diagonal of csm
    result[0] = scalarProd * signalLossNormalization[0]


@nb.guvectorize([(nb.complex128[:,:], nb.complex128[:], nb.float64[:], nb.float64[:])], '(m,m),(m),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_SpecificSteerVec_CsmRemovedDiag(csm, steerVec, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = csm.shape[0]

    # performing matrix-vector-multiplication (see bottom of information header of 'beamformerFreq')
    scalarProd = 0.0
    for cntMics in xrange(nMics):
        leftVecMatrixProd = 0.0 + 0.0j
        for cntMics2 in xrange(cntMics):  # calculate 'steer^H * CSM' of upper-triangular-part of csm (without diagonal)
            leftVecMatrixProd += csm[cntMics2, cntMics] * steerVec[cntMics2].conjugate()
        scalarProd += 2 * (leftVecMatrixProd * steerVec[cntMics]).real  # use that csm is Hermitian (lower triangular of csm can be reduced to factor '2')
    result[0] = scalarProd * signalLossNormalization[0]


#%% beamformers - Eigenvalue Problem

@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(e),(m,e),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_Formulation1AkaClassic_FullCSM(eigVal, eigVec, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = distGridToAllMics.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics]))
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg))

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdFullCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        for cntMics in range(nMics):
            scalarProdFullCSMperEigVal += eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real  
        scalarProdFullCSM += scalarProdFullCSMAbsSquared * eigVal[cntEigVal]
    normalizeFactor = nMics  # specific normalization of steering vector formulation
    result[0] = scalarProdFullCSM / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(e),(m,e),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_Formulation1AkaClassic_CsmRemovedDiag(eigVal, eigVec, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = distGridToAllMics.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics] - distGridToArrayCenter[0]))
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg))

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdReducedCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        scalarProdDiagCSMperEigVal = 0.0
        for cntMics in range(nMics):
            temp1 = eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]  # Dont call it 'expArg' like in steer-loop, because expArg is now a float (no double) which would cause errors of approx 1e-8
            scalarProdFullCSMperEigVal += temp1
            scalarProdDiagCSMperEigVal += (temp1 * temp1.conjugate()).real  
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real
        scalarProdReducedCSM += (scalarProdFullCSMAbsSquared - scalarProdDiagCSMperEigVal) * eigVal[cntEigVal]
    normalizeFactor = nMics  # specific normalization of steering vector formulation
    result[0] = scalarProdReducedCSM / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(e),(m,e),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_Formulation2AkaInverse_FullCSM(eigVal, eigVec, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = distGridToAllMics.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics] - distGridToArrayCenter[0]))
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) * distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdFullCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        for cntMics in range(nMics):
            scalarProdFullCSMperEigVal += eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real  
        scalarProdFullCSM += scalarProdFullCSMAbsSquared * eigVal[cntEigVal]
    normalizeFactor = nMics * distGridToArrayCenter[0]  # specific normalization of steering vector formulation
    result[0] = scalarProdFullCSM / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(e),(m,e),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_Formulation2AkaInverse_CsmRemovedDiag(eigVal, eigVec, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = distGridToAllMics.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics] - distGridToArrayCenter[0]))
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) * distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdReducedCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        scalarProdDiagCSMperEigVal = 0.0
        for cntMics in range(nMics):
            temp1 = eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]  # Dont call it 'expArg' like in steer-loop, because expArg is now a float (no double) which would cause errors of approx 1e-8
            scalarProdFullCSMperEigVal += temp1
            scalarProdDiagCSMperEigVal += (temp1 * temp1.conjugate()).real  
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real
        scalarProdReducedCSM += (scalarProdFullCSMAbsSquared - scalarProdDiagCSMperEigVal) * eigVal[cntEigVal]
    normalizeFactor = nMics * distGridToArrayCenter[0]  # specific normalization of steering vector formulation
    result[0] = scalarProdReducedCSM / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(e),(m,e),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_Formulation3AkaTrueLevel_FullCSM(eigVal, eigVec, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = distGridToAllMics.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    helpNormalize = 0.0
    for cntMics in xrange(nMics):
        helpNormalize += 1.0 / (distGridToAllMics[cntMics] * distGridToAllMics[cntMics])  
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics] - distGridToArrayCenter[0]))
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) / distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdFullCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        for cntMics in range(nMics):
            scalarProdFullCSMperEigVal += eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real  
        scalarProdFullCSM += scalarProdFullCSMAbsSquared * eigVal[cntEigVal]
    normalizeFactor = distGridToArrayCenter[0] * helpNormalize  # specific normalization of steering vector formulation
    result[0] = scalarProdFullCSM / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(e),(m,e),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_Formulation3AkaTrueLevel_CsmRemovedDiag(eigVal, eigVec, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = distGridToAllMics.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    helpNormalize = 0.0
    for cntMics in xrange(nMics):
        helpNormalize += 1.0 / (distGridToAllMics[cntMics] * distGridToAllMics[cntMics])  
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics] - distGridToArrayCenter[0]))
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) / distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdReducedCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        scalarProdDiagCSMperEigVal = 0.0
        for cntMics in range(nMics):
            temp1 = eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]  # Dont call it 'expArg' like in steer-loop, because expArg is now a float (no double) which would cause errors of approx 1e-8
            scalarProdFullCSMperEigVal += temp1
            scalarProdDiagCSMperEigVal += (temp1 * temp1.conjugate()).real  
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real
        scalarProdReducedCSM += (scalarProdFullCSMAbsSquared - scalarProdDiagCSMperEigVal) * eigVal[cntEigVal]
    normalizeFactor = distGridToArrayCenter[0] * helpNormalize  # specific normalization of steering vector formulation
    result[0] = scalarProdReducedCSM / (normalizeFactor * normalizeFactor) * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(e),(m,e),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_Formulation4AkaTrueLocation_FullCSM(eigVal, eigVec, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = distGridToAllMics.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    helpNormalize = 0.0
    for cntMics in xrange(nMics):
        helpNormalize += 1.0 / (distGridToAllMics[cntMics] * distGridToAllMics[cntMics])  
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics] - distGridToArrayCenter[0]))
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) / distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdFullCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        for cntMics in range(nMics):
            scalarProdFullCSMperEigVal += eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real  
        scalarProdFullCSM += scalarProdFullCSMAbsSquared * eigVal[cntEigVal]
    normalizeFactor = nMics * helpNormalize  # specific normalization of steering vector formulation
    result[0] = scalarProdFullCSM / normalizeFactor * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:], nb.float64[:])],
              '(e),(m,e),(),(m),(),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_Formulation4AkaTrueLocation_CsmRemovedDiag(eigVal, eigVec, distGridToArrayCenter, distGridToAllMics, waveNumber, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = distGridToAllMics.shape[0]
    steerVec = np.zeros((nMics), np.complex128)

    # building steering vector: in order to save some operation -> some normalization steps are applied after mat-vec-multipl.
    helpNormalize = 0.0
    for cntMics in xrange(nMics):
        helpNormalize += 1.0 / (distGridToAllMics[cntMics] * distGridToAllMics[cntMics])  
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics] - distGridToArrayCenter[0]))
        steerVec[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) / distGridToAllMics[cntMics]  # r_{t,i}-normalization is handled here

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdReducedCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        scalarProdDiagCSMperEigVal = 0.0
        for cntMics in range(nMics):
            temp1 = eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]  # Dont call it 'expArg' like in steer-loop, because expArg is now a float (no double) which would cause errors of approx 1e-8
            scalarProdFullCSMperEigVal += temp1
            scalarProdDiagCSMperEigVal += (temp1 * temp1.conjugate()).real  
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real
        scalarProdReducedCSM += (scalarProdFullCSMAbsSquared - scalarProdDiagCSMperEigVal) * eigVal[cntEigVal]
    normalizeFactor = nMics * helpNormalize  # specific normalization of steering vector formulation
    result[0] = scalarProdReducedCSM / normalizeFactor * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.complex128[:], nb.float64[:], nb.float64[:])],
                 '(e),(m,e),(m),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_SpecificSteerVec_FullCSM(eigVal, eigVec, steerVec, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = eigVec.shape[0]

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdFullCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        for cntMics in range(nMics):
            scalarProdFullCSMperEigVal += eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real  
        scalarProdFullCSM += scalarProdFullCSMAbsSquared * eigVal[cntEigVal]
    result[0] = scalarProdFullCSM * signalLossNormalization[0]


@nb.guvectorize([(nb.float64[:], nb.complex128[:,:], nb.complex128[:], nb.float64[:], nb.float64[:])],
                 '(e),(m,e),(m),()->()', nopython=True, target=parallelOption, cache=cachedOption)
def _freqBeamformer_EigValProb_SpecificSteerVec_CsmRemovedDiag(eigVal, eigVec, steerVec, signalLossNormalization, result):
    # see bottom of information header of 'beamformerFreq' for information on which steps are taken, in order to gain speed improvements.
    nMics = eigVec.shape[0]

    # performing matrix-vector-multplication via spectral decomp. (see bottom of information header of 'beamformerFreq')
    scalarProdReducedCSM = 0.0
    for cntEigVal in range(len(eigVal)):
        scalarProdFullCSMperEigVal = 0.0 + 0.0j
        scalarProdDiagCSMperEigVal = 0.0
        for cntMics in range(nMics):
            temp1 = eigVec[cntMics, cntEigVal].conjugate() * steerVec[cntMics]
            scalarProdFullCSMperEigVal += temp1
            scalarProdDiagCSMperEigVal += (temp1 * temp1.conjugate()).real  
        scalarProdFullCSMAbsSquared = (scalarProdFullCSMperEigVal * scalarProdFullCSMperEigVal.conjugate()).real
        scalarProdReducedCSM += (scalarProdFullCSMAbsSquared - scalarProdDiagCSMperEigVal) * eigVal[cntEigVal]
    result[0] = scalarProdReducedCSM * signalLossNormalization[0]


#%% Transfer - Function
def transfer(distGridToArrayCenter, distGridToAllMics, wavenumber):
    """ Calculates the transfer functions between the various mics and gridpoints.
    
    Input
    -----
        ``distGridToArrayCenter`` ... float64[nGridpoints]

        ``distGridToAllMics`` ... float64[nGridpoints, nMics]

        ``wavenumber`` ... complex128[nFreqs] (the wavenumber should be stored in the imag-part)
    
    Returns
    -------
        The Transferfunctions in format complex128[nFreqs, nGridPoints, nMics].
    """
    nFreqs, nGridPoints, nMics = wavenumber.shape[0], distGridToAllMics.shape[0], distGridToAllMics.shape[1]
    # transfer routine: parallelized over Gridpoints
    transferOutput = np.zeros((nFreqs, nGridPoints, nMics), np.complex128)
    for cntFreqs in xrange(nFreqs):
        result = np.zeros((nGridPoints, nMics), np.complex128)
        _transferCoreFunc(distGridToArrayCenter, distGridToAllMics, wavenumber[cntFreqs].imag, result)
        transferOutput[cntFreqs, :, :] = result
    return transferOutput

@nb.guvectorize([(nb.float64[:], nb.float64[:], nb.float64[:], nb.complex128[:])], '(),(m),()->(m)', nopython=True, target=parallelOption, cache=cachedOption)
def _transferCoreFunc(distGridToArrayCenter, distGridToAllMics, waveNumber, result):
    nMics = distGridToAllMics.shape[0]
    for cntMics in xrange(nMics):
        expArg = np.float32(waveNumber[0] * (distGridToAllMics[cntMics] - distGridToArrayCenter[0]))  # FLOAT32 ODER FLOAT64?
        result[cntMics] = (np.cos(expArg) - 1j * np.sin(expArg)) * distGridToArrayCenter[0] / distGridToAllMics[cntMics]