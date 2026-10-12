/** OHIF viewer settings for CIDMS. The viewer is served by the app at /viewer/ and reads images only
 * through the app's DICOMweb proxy (/api/dicom-web), which uses the signed-in person's session and only ever
 * serves their own centre's studies. No study list: it opens the study it is given (?StudyInstanceUIDs=). */
window.config = {
  routerBasename: '/viewer',
  showStudyList: false,
  extensions: [],
  modes: [],
  customizationService: {},
  maxNumberOfWebWorkers: 3,
  showWarningMessageForCrossOrigin: false,
  showCPUFallbackMessage: true,
  showLoadingIndicator: true,
  strictZSpacingForVolumeViewport: true,
  maxNumRequests: { interaction: 100, thumbnail: 5, prefetch: 10 },
  showErrorDetails: 'production',
  investigationalUseDialog: { option: 'never' },
  defaultDataSourceName: 'supreme',
  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'supreme',
      configuration: {
        friendlyName: 'CIDMS',
        name: 'supreme',
        wadoUriRoot: window.location.origin + '/api/dicom-web',
        qidoRoot: window.location.origin + '/api/dicom-web',
        wadoRoot: window.location.origin + '/api/dicom-web',
        qidoSupportsIncludeField: false,
        supportsReject: false,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        staticWado: true,
        singlepart: 'bulkdata,video',
        bulkDataURI: { enabled: true, relativeResolution: 'studies' },
        omitQuotationForMultipartRequest: true,
      },
    },
  ],
};
