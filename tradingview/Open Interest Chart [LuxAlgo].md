// This work is licensed under a Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) https://creativecommons.org/licenses/by-nc-sa/4.0/
// © LuxAlgo

//@version=5
indicator('Open Interest Chart [LuxAlgo]', shorttitle='LuxAlgo - Open Interest Chart', max_bars_back=1000)

cm   = ' - CME'
co   = ' - COMEX'
ny   = ' - NYMEX'
cb   = ' - CBOT'
cbo  = ' - CBOE'
us   = ' - ICE U.S.'
mg   = ' - MGEX'

a    = ' - Futures - Open Interest (All)'
old  = ' - Futures - Open Interest (Old)'
oth  = ' - Futures - Open Interest (Other)'

c    = 'COT'
c2   = 'COT2'
c3   = 'COT3'
c4   = 'COT4'
c5   = 'COT5'

f    = '_F_OI'
fold = '_F_OI_OLD'
foth = '_F_OI_OTHER'

//------------------------------------------------------------------------------
//Settings
//-----------------------------------------------------------------------------{
ac1  = input.bool  (true                                                     , ''                                  , inline='1', group='Tickers')
ch1  = input.string(c +':Bitcoin'+cm+a                                       , '1'                                 , inline='1', group='Tickers'
     , options = 
      [ 
       c +':30-Day Federal Funds'+cb+a   , c3+':30-Day Federal Funds'+cb+a   , c +':30-Day Federal Funds'+cb+old
     , c +':1-Month SOFR'+cm+a           , c3+':1-Month SOFR'+cm+a           , c +':1-Month SOFR'+cm+old 
     , c +':3-Month SOFR'+cm+a           , c3+':3-Month SOFR'+cm+a           , c +':3-Month SOFR'+cm+old 
     , c +':Bitcoin'+cm+a                , c3+':Bitcoin'+cm+a                , c +':Bitcoin'+cm+old            
     , c +':Brazilian Real'+cm+a         , c3+':Brazilian Real'+cm+a         , c +':Brazilian Real'+cm+old     
     , c +':Canadian Dollar'+cm+a        , c3+':Canadian Dollar'+cm+a        , c +':Canadian Dollar'+cm+old   
     , c +':Canola'+us+a                 , c2+':Canola'+us+a                 , c +':Canola'+us+old                 , c2+':Canola'+us+old  
     , c +':CME Milk IV'+cm+a            , c2+':CME Milk IV'+cm+a            , c +':CME Milk IV'+cm+old            , c2+':CME Milk IV'+cm+old  
     , c +':Cocoa'+us+a                  , c2+':Cocoa'+us+a                  , c +':Cocoa'+us+old                  , c2+':Cocoa'+us+old  
     , c +':Coffee C'+us+a               , c2+':Coffee C'+us+a               , c +':Coffee C'+us+old               , c2+':Coffee C'+us+old        
     , c +':Corn'+cb+a                   , c2+':Corn'+cb+a                   , c +':Corn'+cb+old                   , c2+':Corn'+cb+old  
     , c +':Cotton No. 2'+us+a           , c2+':Cotton No. 2'+us+a           , c +':Cotton No. 2'+us+old           , c2+':Cotton No. 2'+us+old    
     , c +':Dry Whey'+cm+a               , c2+':Dry Whey'+cm+a               , c +':Dry Whey'+cm+old               , c2+':Dry Whey'+cm+old  
     , c +':Euro FX'+cm+a                , c3+':Euro FX'+cm+a                , c +':Euro FX'+cm+old      
     , c +':Gold'+co+a                   , c +':Gold'+co+old      
     , c +':Japanese Yen'+cm+a           , c3+':Japanese Yen'+cm+a           , c +':Japanese Yen'+cm+old     
     , c +':Lean Hogs'+cm+a              , c2+':Lean Hogs'+cm+a              , c +':Lean Hogs'+cm+old              , c2+':Lean Hogs'+cm+old 
     , c +':Live Cattle'+cm+a            , c2+':Live Cattle'+cm+a            , c +':Live Cattle'+cm+old            , c2+':Live Cattle'+cm+old
     , c +':Mexican Peso'+cm+a           , c3+':Mexican Peso'+cm+a           , c +':Mexican Peso'+cm+old     
     , c +':Micro Bitcoin'+cm+a          , c3+':Micro Bitcoin'+cm+a          , c +':Micro Bitcoin'+cm+old                   
     , c +':Micro Gold'+co+a             , c +':Micro Gold'+co+old              
     , c +':Milk Class III'+cm+a         , c2+':Milk Class III'+cm+a         , c +':Milk Class III'+cm+old         , c2+':Milk Class III'+cm+old 
     , c +':Nasdaq-100 Consolidated'+cm+a, c3+':Nasdaq-100 Consolidated'+cm+a, c +':Nasdaq-100 Consolidated'+cm+old   
     , c +':Nasdaq-100 Stock Index'+cm+a , c3+':Nasdaq-100 Stock Index'+cm+a , c +':Nasdaq-100 Stock Index'+cm+old       
     , c +':Natural Gas'+ny+a            , c2+':Natural Gas'+ny+a            , c +':Natural Gas'+ny+old            , c2+':Natural Gas'+ny+old      
     , c +':Non Fat Dry Milk'+cm+a       , c2+':Non Fat Dry Milk'+cm+a       , c +':Non Fat Dry Milk'+cm+old       , c2+':Non Fat Dry Milk'+cm+old 
     , c +':Oats'+cb+a                   , c2+':Oats'+cb+a                   , c +':Oats'+cb+old                   , c2+':Oats'+cb+old              
     , c +':Palladium'+ny+a              , c +':Palladium'+ny+old
     , c +':Platinum'+ny+a               , c2+':Platinum'+ny+a               , c +':Platinum'+ny+old               , c2+':Platinum'+ny+old 
     , c +':Rough Rice'+cb+a             , c2+':Rough Rice'+cb+a             , c +':Rough Rice'+cb+old             , c2+':Rough Rice'+cb+old  
     , c +':Russell 2000 Index'+cm+a     , c3+':Russell 2000 Index'+cm+a     , c +':Russell 2000 Index'+cm+old     
     , c +':Russian Ruble'+cm+a          , c3+':Russian Ruble'+cm+a          , c +':Russian Ruble'+cm+old     
     , c +':S&P 500 Consolidated'+cm+a   , c3+':S&P 500 Consolidated'+cm+a   , c +':S&P 500 Consolidated'+cm+old    
     , c +':S&P 500 Stock Index'+cm+a    , c3+':S&P 500 Stock Index'+cm+a    , c +':S&P 500 Stock Index'+cm+old    
     , c +':Silver'+co+a                 , c2+':Silver'+co+a                 , c +':Silver'+co+old                 , c2+':Silver'+co+old 
     , c +':Soybeans'+cb+a               , c2+':Soybeans'+cb+a               , c +':Soybeans'+cb+old               , c2+':Soybeans'+cb+old  
     , c +':Sugar No. 11'+us+a           , c2+':Sugar No. 11'+us+a           , c +':Sugar No. 11'+us+old           , c2+':Sugar No. 11'+us+old    
     , c +':Swiss Franc'+cm+a            , c3+':Swiss Franc'+cm+a            , c +':Swiss Franc'+cm+old     
     , c +':U.S. Dollar Index'+us+a      , c3+':U.S. Dollar Index'+us+a      , c +':U.S. Dollar Index'+us+old 
     , c +':U.S. Treasury Bonds'+cb+a    , c3+':U.S. Treasury Bonds'+cb+a    , c +':U.S. Treasury Bonds'+cb+old  
     , c +':VIX Futures'+cbo+a           , c3+':VIX Futures'+cbo+a           , c +':VIX Futures'+cbo+old 
     , c +':Wheat HRW'+co+a              , c2+':Wheat HRW'+co+a              , c +':Wheat HRW'+co+old              , c2+':Wheat HRW'+co+old    
     , c +':Wheat HRSPRING'+mg+a         , c2+':Wheat HRSPRING'+mg+a         , c +':Wheat HRSPRING'+mg+old         , c2+':Wheat HRSPRING'+mg+old    
     , c +':Wheat SRW'+co+a              , c2+':Wheat SRW'+co+a              , c +':Wheat SRW'+co+old              , c2+':Wheat SRW'+co+old    
      ]
     )
sm1  = input.symbol    (''                                                   , ''                                  , inline='1', group='Tickers')
res1 = input.timeframe ('D'                                                  , ''                                  , inline='1', group='Tickers')

ac2  = input.bool  (true                                                     , ''                                  , inline='2', group='Tickers')
ch2  = input.string(c +':U.S. Dollar Index'+us+a                             , '2'                                 , inline='2', group='Tickers'
     , options = 
      [ 
       c +':30-Day Federal Funds'+cb+a   , c3+':30-Day Federal Funds'+cb+a   , c +':30-Day Federal Funds'+cb+old
     , c +':1-Month SOFR'+cm+a           , c3+':1-Month SOFR'+cm+a           , c +':1-Month SOFR'+cm+old 
     , c +':3-Month SOFR'+cm+a           , c3+':3-Month SOFR'+cm+a           , c +':3-Month SOFR'+cm+old 
     , c +':Bitcoin'+cm+a                , c3+':Bitcoin'+cm+a                , c +':Bitcoin'+cm+old            
     , c +':Brazilian Real'+cm+a         , c3+':Brazilian Real'+cm+a         , c +':Brazilian Real'+cm+old     
     , c +':Canadian Dollar'+cm+a        , c3+':Canadian Dollar'+cm+a        , c +':Canadian Dollar'+cm+old   
     , c +':Canola'+us+a                 , c2+':Canola'+us+a                 , c +':Canola'+us+old                 , c2+':Canola'+us+old  
     , c +':CME Milk IV'+cm+a            , c2+':CME Milk IV'+cm+a            , c +':CME Milk IV'+cm+old            , c2+':CME Milk IV'+cm+old  
     , c +':Cocoa'+us+a                  , c2+':Cocoa'+us+a                  , c +':Cocoa'+us+old                  , c2+':Cocoa'+us+old  
     , c +':Coffee C'+us+a               , c2+':Coffee C'+us+a               , c +':Coffee C'+us+old               , c2+':Coffee C'+us+old        
     , c +':Corn'+cb+a                   , c2+':Corn'+cb+a                   , c +':Corn'+cb+old                   , c2+':Corn'+cb+old  
     , c +':Cotton No. 2'+us+a           , c2+':Cotton No. 2'+us+a           , c +':Cotton No. 2'+us+old           , c2+':Cotton No. 2'+us+old    
     , c +':Dry Whey'+cm+a               , c2+':Dry Whey'+cm+a               , c +':Dry Whey'+cm+old               , c2+':Dry Whey'+cm+old  
     , c +':Euro FX'+cm+a                , c3+':Euro FX'+cm+a                , c +':Euro FX'+cm+old      
     , c +':Gold'+co+a                   , c +':Gold'+co+old      
     , c +':Japanese Yen'+cm+a           , c3+':Japanese Yen'+cm+a           , c +':Japanese Yen'+cm+old     
     , c +':Lean Hogs'+cm+a              , c2+':Lean Hogs'+cm+a              , c +':Lean Hogs'+cm+old              , c2+':Lean Hogs'+cm+old 
     , c +':Live Cattle'+cm+a            , c2+':Live Cattle'+cm+a            , c +':Live Cattle'+cm+old            , c2+':Live Cattle'+cm+old
     , c +':Mexican Peso'+cm+a           , c3+':Mexican Peso'+cm+a           , c +':Mexican Peso'+cm+old     
     , c +':Micro Bitcoin'+cm+a          , c3+':Micro Bitcoin'+cm+a          , c +':Micro Bitcoin'+cm+old                   
     , c +':Micro Gold'+co+a             , c +':Micro Gold'+co+old              
     , c +':Milk Class III'+cm+a         , c2+':Milk Class III'+cm+a         , c +':Milk Class III'+cm+old         , c2+':Milk Class III'+cm+old 
     , c +':Nasdaq-100 Consolidated'+cm+a, c3+':Nasdaq-100 Consolidated'+cm+a, c +':Nasdaq-100 Consolidated'+cm+old   
     , c +':Nasdaq-100 Stock Index'+cm+a , c3+':Nasdaq-100 Stock Index'+cm+a , c +':Nasdaq-100 Stock Index'+cm+old       
     , c +':Natural Gas'+ny+a            , c2+':Natural Gas'+ny+a            , c +':Natural Gas'+ny+old            , c2+':Natural Gas'+ny+old      
     , c +':Non Fat Dry Milk'+cm+a       , c2+':Non Fat Dry Milk'+cm+a       , c +':Non Fat Dry Milk'+cm+old       , c2+':Non Fat Dry Milk'+cm+old 
     , c +':Oats'+cb+a                   , c2+':Oats'+cb+a                   , c +':Oats'+cb+old                   , c2+':Oats'+cb+old              
     , c +':Palladium'+ny+a              , c +':Palladium'+ny+old
     , c +':Platinum'+ny+a               , c2+':Platinum'+ny+a               , c +':Platinum'+ny+old               , c2+':Platinum'+ny+old 
     , c +':Rough Rice'+cb+a             , c2+':Rough Rice'+cb+a             , c +':Rough Rice'+cb+old             , c2+':Rough Rice'+cb+old  
     , c +':Russell 2000 Index'+cm+a     , c3+':Russell 2000 Index'+cm+a     , c +':Russell 2000 Index'+cm+old     
     , c +':Russian Ruble'+cm+a          , c3+':Russian Ruble'+cm+a          , c +':Russian Ruble'+cm+old     
     , c +':S&P 500 Consolidated'+cm+a   , c3+':S&P 500 Consolidated'+cm+a   , c +':S&P 500 Consolidated'+cm+old    
     , c +':S&P 500 Stock Index'+cm+a    , c3+':S&P 500 Stock Index'+cm+a    , c +':S&P 500 Stock Index'+cm+old    
     , c +':Silver'+co+a                 , c2+':Silver'+co+a                 , c +':Silver'+co+old                 , c2+':Silver'+co+old 
     , c +':Soybeans'+cb+a               , c2+':Soybeans'+cb+a               , c +':Soybeans'+cb+old               , c2+':Soybeans'+cb+old  
     , c +':Sugar No. 11'+us+a           , c2+':Sugar No. 11'+us+a           , c +':Sugar No. 11'+us+old           , c2+':Sugar No. 11'+us+old    
     , c +':Swiss Franc'+cm+a            , c3+':Swiss Franc'+cm+a            , c +':Swiss Franc'+cm+old     
     , c +':U.S. Dollar Index'+us+a      , c3+':U.S. Dollar Index'+us+a      , c +':U.S. Dollar Index'+us+old 
     , c +':U.S. Treasury Bonds'+cb+a    , c3+':U.S. Treasury Bonds'+cb+a    , c +':U.S. Treasury Bonds'+cb+old  
     , c +':VIX Futures'+cbo+a           , c3+':VIX Futures'+cbo+a           , c +':VIX Futures'+cbo+old 
     , c +':Wheat HRW'+co+a              , c2+':Wheat HRW'+co+a              , c +':Wheat HRW'+co+old              , c2+':Wheat HRW'+co+old    
     , c +':Wheat HRSPRING'+mg+a         , c2+':Wheat HRSPRING'+mg+a         , c +':Wheat HRSPRING'+mg+old         , c2+':Wheat HRSPRING'+mg+old    
     , c +':Wheat SRW'+co+a              , c2+':Wheat SRW'+co+a              , c +':Wheat SRW'+co+old              , c2+':Wheat SRW'+co+old    
      ]
     )
sm2  = input.symbol    (''                                                   , ''                                  , inline='2', group='Tickers')
res2 = input.timeframe ('D'                                                  , ''                                  , inline='2', group='Tickers')

ac3  = input.bool  (true                                                     , ''                                  , inline='3', group='Tickers')
ch3  = input.string(c +':Gold'+co+a                                          , '3'                                 , inline='3', group='Tickers'
     , options = 
      [ 
       c +':30-Day Federal Funds'+cb+a   , c3+':30-Day Federal Funds'+cb+a   , c +':30-Day Federal Funds'+cb+old
     , c +':1-Month SOFR'+cm+a           , c3+':1-Month SOFR'+cm+a           , c +':1-Month SOFR'+cm+old 
     , c +':3-Month SOFR'+cm+a           , c3+':3-Month SOFR'+cm+a           , c +':3-Month SOFR'+cm+old 
     , c +':Bitcoin'+cm+a                , c3+':Bitcoin'+cm+a                , c +':Bitcoin'+cm+old            
     , c +':Brazilian Real'+cm+a         , c3+':Brazilian Real'+cm+a         , c +':Brazilian Real'+cm+old     
     , c +':Canadian Dollar'+cm+a        , c3+':Canadian Dollar'+cm+a        , c +':Canadian Dollar'+cm+old   
     , c +':Canola'+us+a                 , c2+':Canola'+us+a                 , c +':Canola'+us+old                 , c2+':Canola'+us+old  
     , c +':CME Milk IV'+cm+a            , c2+':CME Milk IV'+cm+a            , c +':CME Milk IV'+cm+old            , c2+':CME Milk IV'+cm+old  
     , c +':Cocoa'+us+a                  , c2+':Cocoa'+us+a                  , c +':Cocoa'+us+old                  , c2+':Cocoa'+us+old  
     , c +':Coffee C'+us+a               , c2+':Coffee C'+us+a               , c +':Coffee C'+us+old               , c2+':Coffee C'+us+old        
     , c +':Corn'+cb+a                   , c2+':Corn'+cb+a                   , c +':Corn'+cb+old                   , c2+':Corn'+cb+old  
     , c +':Cotton No. 2'+us+a           , c2+':Cotton No. 2'+us+a           , c +':Cotton No. 2'+us+old           , c2+':Cotton No. 2'+us+old    
     , c +':Dry Whey'+cm+a               , c2+':Dry Whey'+cm+a               , c +':Dry Whey'+cm+old               , c2+':Dry Whey'+cm+old  
     , c +':Euro FX'+cm+a                , c3+':Euro FX'+cm+a                , c +':Euro FX'+cm+old      
     , c +':Gold'+co+a                   , c +':Gold'+co+old      
     , c +':Japanese Yen'+cm+a           , c3+':Japanese Yen'+cm+a           , c +':Japanese Yen'+cm+old     
     , c +':Lean Hogs'+cm+a              , c2+':Lean Hogs'+cm+a              , c +':Lean Hogs'+cm+old              , c2+':Lean Hogs'+cm+old 
     , c +':Live Cattle'+cm+a            , c2+':Live Cattle'+cm+a            , c +':Live Cattle'+cm+old            , c2+':Live Cattle'+cm+old
     , c +':Mexican Peso'+cm+a           , c3+':Mexican Peso'+cm+a           , c +':Mexican Peso'+cm+old     
     , c +':Micro Bitcoin'+cm+a          , c3+':Micro Bitcoin'+cm+a          , c +':Micro Bitcoin'+cm+old                   
     , c +':Micro Gold'+co+a             , c +':Micro Gold'+co+old              
     , c +':Milk Class III'+cm+a         , c2+':Milk Class III'+cm+a         , c +':Milk Class III'+cm+old         , c2+':Milk Class III'+cm+old 
     , c +':Nasdaq-100 Consolidated'+cm+a, c3+':Nasdaq-100 Consolidated'+cm+a, c +':Nasdaq-100 Consolidated'+cm+old   
     , c +':Nasdaq-100 Stock Index'+cm+a , c3+':Nasdaq-100 Stock Index'+cm+a , c +':Nasdaq-100 Stock Index'+cm+old       
     , c +':Natural Gas'+ny+a            , c2+':Natural Gas'+ny+a            , c +':Natural Gas'+ny+old            , c2+':Natural Gas'+ny+old      
     , c +':Non Fat Dry Milk'+cm+a       , c2+':Non Fat Dry Milk'+cm+a       , c +':Non Fat Dry Milk'+cm+old       , c2+':Non Fat Dry Milk'+cm+old 
     , c +':Oats'+cb+a                   , c2+':Oats'+cb+a                   , c +':Oats'+cb+old                   , c2+':Oats'+cb+old              
     , c +':Palladium'+ny+a              , c +':Palladium'+ny+old
     , c +':Platinum'+ny+a               , c2+':Platinum'+ny+a               , c +':Platinum'+ny+old               , c2+':Platinum'+ny+old 
     , c +':Rough Rice'+cb+a             , c2+':Rough Rice'+cb+a             , c +':Rough Rice'+cb+old             , c2+':Rough Rice'+cb+old  
     , c +':Russell 2000 Index'+cm+a     , c3+':Russell 2000 Index'+cm+a     , c +':Russell 2000 Index'+cm+old     
     , c +':Russian Ruble'+cm+a          , c3+':Russian Ruble'+cm+a          , c +':Russian Ruble'+cm+old     
     , c +':S&P 500 Consolidated'+cm+a   , c3+':S&P 500 Consolidated'+cm+a   , c +':S&P 500 Consolidated'+cm+old    
     , c +':S&P 500 Stock Index'+cm+a    , c3+':S&P 500 Stock Index'+cm+a    , c +':S&P 500 Stock Index'+cm+old    
     , c +':Silver'+co+a                 , c2+':Silver'+co+a                 , c +':Silver'+co+old                 , c2+':Silver'+co+old 
     , c +':Soybeans'+cb+a               , c2+':Soybeans'+cb+a               , c +':Soybeans'+cb+old               , c2+':Soybeans'+cb+old  
     , c +':Sugar No. 11'+us+a           , c2+':Sugar No. 11'+us+a           , c +':Sugar No. 11'+us+old           , c2+':Sugar No. 11'+us+old    
     , c +':Swiss Franc'+cm+a            , c3+':Swiss Franc'+cm+a            , c +':Swiss Franc'+cm+old     
     , c +':U.S. Dollar Index'+us+a      , c3+':U.S. Dollar Index'+us+a      , c +':U.S. Dollar Index'+us+old 
     , c +':U.S. Treasury Bonds'+cb+a    , c3+':U.S. Treasury Bonds'+cb+a    , c +':U.S. Treasury Bonds'+cb+old  
     , c +':VIX Futures'+cbo+a           , c3+':VIX Futures'+cbo+a           , c +':VIX Futures'+cbo+old 
     , c +':Wheat HRW'+co+a              , c2+':Wheat HRW'+co+a              , c +':Wheat HRW'+co+old              , c2+':Wheat HRW'+co+old    
     , c +':Wheat HRSPRING'+mg+a         , c2+':Wheat HRSPRING'+mg+a         , c +':Wheat HRSPRING'+mg+old         , c2+':Wheat HRSPRING'+mg+old    
     , c +':Wheat SRW'+co+a              , c2+':Wheat SRW'+co+a              , c +':Wheat SRW'+co+old              , c2+':Wheat SRW'+co+old    
      ]
     )
sm3  = input.symbol    (''                                                   , ''                                  , inline='3', group='Tickers')
res3 = input.timeframe ('D'                                                  , ''                                  , inline='3', group='Tickers')

ac4  = input.bool  (true                                                     , ''                                  , inline='4', group='Tickers')
ch4  = input.string(c +':Natural Gas'+ny+a                                   , '4'                                 , inline='4', group='Tickers'
     , options = 
      [ 
       c +':30-Day Federal Funds'+cb+a   , c3+':30-Day Federal Funds'+cb+a   , c +':30-Day Federal Funds'+cb+old
     , c +':1-Month SOFR'+cm+a           , c3+':1-Month SOFR'+cm+a           , c +':1-Month SOFR'+cm+old 
     , c +':3-Month SOFR'+cm+a           , c3+':3-Month SOFR'+cm+a           , c +':3-Month SOFR'+cm+old 
     , c +':Bitcoin'+cm+a                , c3+':Bitcoin'+cm+a                , c +':Bitcoin'+cm+old            
     , c +':Brazilian Real'+cm+a         , c3+':Brazilian Real'+cm+a         , c +':Brazilian Real'+cm+old     
     , c +':Canadian Dollar'+cm+a        , c3+':Canadian Dollar'+cm+a        , c +':Canadian Dollar'+cm+old   
     , c +':Canola'+us+a                 , c2+':Canola'+us+a                 , c +':Canola'+us+old                 , c2+':Canola'+us+old  
     , c +':CME Milk IV'+cm+a            , c2+':CME Milk IV'+cm+a            , c +':CME Milk IV'+cm+old            , c2+':CME Milk IV'+cm+old  
     , c +':Cocoa'+us+a                  , c2+':Cocoa'+us+a                  , c +':Cocoa'+us+old                  , c2+':Cocoa'+us+old  
     , c +':Coffee C'+us+a               , c2+':Coffee C'+us+a               , c +':Coffee C'+us+old               , c2+':Coffee C'+us+old        
     , c +':Corn'+cb+a                   , c2+':Corn'+cb+a                   , c +':Corn'+cb+old                   , c2+':Corn'+cb+old  
     , c +':Cotton No. 2'+us+a           , c2+':Cotton No. 2'+us+a           , c +':Cotton No. 2'+us+old           , c2+':Cotton No. 2'+us+old    
     , c +':Dry Whey'+cm+a               , c2+':Dry Whey'+cm+a               , c +':Dry Whey'+cm+old               , c2+':Dry Whey'+cm+old  
     , c +':Euro FX'+cm+a                , c3+':Euro FX'+cm+a                , c +':Euro FX'+cm+old      
     , c +':Gold'+co+a                   , c +':Gold'+co+old      
     , c +':Japanese Yen'+cm+a           , c3+':Japanese Yen'+cm+a           , c +':Japanese Yen'+cm+old     
     , c +':Lean Hogs'+cm+a              , c2+':Lean Hogs'+cm+a              , c +':Lean Hogs'+cm+old              , c2+':Lean Hogs'+cm+old 
     , c +':Live Cattle'+cm+a            , c2+':Live Cattle'+cm+a            , c +':Live Cattle'+cm+old            , c2+':Live Cattle'+cm+old
     , c +':Mexican Peso'+cm+a           , c3+':Mexican Peso'+cm+a           , c +':Mexican Peso'+cm+old     
     , c +':Micro Bitcoin'+cm+a          , c3+':Micro Bitcoin'+cm+a          , c +':Micro Bitcoin'+cm+old                   
     , c +':Micro Gold'+co+a             , c +':Micro Gold'+co+old              
     , c +':Milk Class III'+cm+a         , c2+':Milk Class III'+cm+a         , c +':Milk Class III'+cm+old         , c2+':Milk Class III'+cm+old 
     , c +':Nasdaq-100 Consolidated'+cm+a, c3+':Nasdaq-100 Consolidated'+cm+a, c +':Nasdaq-100 Consolidated'+cm+old   
     , c +':Nasdaq-100 Stock Index'+cm+a , c3+':Nasdaq-100 Stock Index'+cm+a , c +':Nasdaq-100 Stock Index'+cm+old       
     , c +':Natural Gas'+ny+a            , c2+':Natural Gas'+ny+a            , c +':Natural Gas'+ny+old            , c2+':Natural Gas'+ny+old      
     , c +':Non Fat Dry Milk'+cm+a       , c2+':Non Fat Dry Milk'+cm+a       , c +':Non Fat Dry Milk'+cm+old       , c2+':Non Fat Dry Milk'+cm+old 
     , c +':Oats'+cb+a                   , c2+':Oats'+cb+a                   , c +':Oats'+cb+old                   , c2+':Oats'+cb+old              
     , c +':Palladium'+ny+a              , c +':Palladium'+ny+old
     , c +':Platinum'+ny+a               , c2+':Platinum'+ny+a               , c +':Platinum'+ny+old               , c2+':Platinum'+ny+old 
     , c +':Rough Rice'+cb+a             , c2+':Rough Rice'+cb+a             , c +':Rough Rice'+cb+old             , c2+':Rough Rice'+cb+old  
     , c +':Russell 2000 Index'+cm+a     , c3+':Russell 2000 Index'+cm+a     , c +':Russell 2000 Index'+cm+old     
     , c +':Russian Ruble'+cm+a          , c3+':Russian Ruble'+cm+a          , c +':Russian Ruble'+cm+old     
     , c +':S&P 500 Consolidated'+cm+a   , c3+':S&P 500 Consolidated'+cm+a   , c +':S&P 500 Consolidated'+cm+old    
     , c +':S&P 500 Stock Index'+cm+a    , c3+':S&P 500 Stock Index'+cm+a    , c +':S&P 500 Stock Index'+cm+old    
     , c +':Silver'+co+a                 , c2+':Silver'+co+a                 , c +':Silver'+co+old                 , c2+':Silver'+co+old 
     , c +':Soybeans'+cb+a               , c2+':Soybeans'+cb+a               , c +':Soybeans'+cb+old               , c2+':Soybeans'+cb+old  
     , c +':Sugar No. 11'+us+a           , c2+':Sugar No. 11'+us+a           , c +':Sugar No. 11'+us+old           , c2+':Sugar No. 11'+us+old    
     , c +':Swiss Franc'+cm+a            , c3+':Swiss Franc'+cm+a            , c +':Swiss Franc'+cm+old     
     , c +':U.S. Dollar Index'+us+a      , c3+':U.S. Dollar Index'+us+a      , c +':U.S. Dollar Index'+us+old 
     , c +':U.S. Treasury Bonds'+cb+a    , c3+':U.S. Treasury Bonds'+cb+a    , c +':U.S. Treasury Bonds'+cb+old  
     , c +':VIX Futures'+cbo+a           , c3+':VIX Futures'+cbo+a           , c +':VIX Futures'+cbo+old 
     , c +':Wheat HRW'+co+a              , c2+':Wheat HRW'+co+a              , c +':Wheat HRW'+co+old              , c2+':Wheat HRW'+co+old    
     , c +':Wheat HRSPRING'+mg+a         , c2+':Wheat HRSPRING'+mg+a         , c +':Wheat HRSPRING'+mg+old         , c2+':Wheat HRSPRING'+mg+old    
     , c +':Wheat SRW'+co+a              , c2+':Wheat SRW'+co+a              , c +':Wheat SRW'+co+old              , c2+':Wheat SRW'+co+old    
      ]
     )
sm4  = input.symbol    (''                                                   , ''                                  , inline='4', group='Tickers')
res4 = input.timeframe ('D'                                                  , ''                                  , inline='4', group='Tickers')

ac5  = input.bool  (true                                                     , ''                                  , inline='5', group='Tickers')
ch5  = input.string(c +':S&P 500 Stock Index'+cm+a                           , '5'                                 , inline='5', group='Tickers'
     , options = 
      [ 
       c +':30-Day Federal Funds'+cb+a   , c3+':30-Day Federal Funds'+cb+a   , c +':30-Day Federal Funds'+cb+old
     , c +':1-Month SOFR'+cm+a           , c3+':1-Month SOFR'+cm+a           , c +':1-Month SOFR'+cm+old 
     , c +':3-Month SOFR'+cm+a           , c3+':3-Month SOFR'+cm+a           , c +':3-Month SOFR'+cm+old 
     , c +':Bitcoin'+cm+a                , c3+':Bitcoin'+cm+a                , c +':Bitcoin'+cm+old            
     , c +':Brazilian Real'+cm+a         , c3+':Brazilian Real'+cm+a         , c +':Brazilian Real'+cm+old     
     , c +':Canadian Dollar'+cm+a        , c3+':Canadian Dollar'+cm+a        , c +':Canadian Dollar'+cm+old   
     , c +':Canola'+us+a                 , c2+':Canola'+us+a                 , c +':Canola'+us+old                 , c2+':Canola'+us+old  
     , c +':CME Milk IV'+cm+a            , c2+':CME Milk IV'+cm+a            , c +':CME Milk IV'+cm+old            , c2+':CME Milk IV'+cm+old  
     , c +':Cocoa'+us+a                  , c2+':Cocoa'+us+a                  , c +':Cocoa'+us+old                  , c2+':Cocoa'+us+old  
     , c +':Coffee C'+us+a               , c2+':Coffee C'+us+a               , c +':Coffee C'+us+old               , c2+':Coffee C'+us+old        
     , c +':Corn'+cb+a                   , c2+':Corn'+cb+a                   , c +':Corn'+cb+old                   , c2+':Corn'+cb+old  
     , c +':Cotton No. 2'+us+a           , c2+':Cotton No. 2'+us+a           , c +':Cotton No. 2'+us+old           , c2+':Cotton No. 2'+us+old    
     , c +':Dry Whey'+cm+a               , c2+':Dry Whey'+cm+a               , c +':Dry Whey'+cm+old               , c2+':Dry Whey'+cm+old  
     , c +':Euro FX'+cm+a                , c3+':Euro FX'+cm+a                , c +':Euro FX'+cm+old      
     , c +':Gold'+co+a                   , c +':Gold'+co+old      
     , c +':Japanese Yen'+cm+a           , c3+':Japanese Yen'+cm+a           , c +':Japanese Yen'+cm+old     
     , c +':Lean Hogs'+cm+a              , c2+':Lean Hogs'+cm+a              , c +':Lean Hogs'+cm+old              , c2+':Lean Hogs'+cm+old 
     , c +':Live Cattle'+cm+a            , c2+':Live Cattle'+cm+a            , c +':Live Cattle'+cm+old            , c2+':Live Cattle'+cm+old
     , c +':Mexican Peso'+cm+a           , c3+':Mexican Peso'+cm+a           , c +':Mexican Peso'+cm+old     
     , c +':Micro Bitcoin'+cm+a          , c3+':Micro Bitcoin'+cm+a          , c +':Micro Bitcoin'+cm+old                   
     , c +':Micro Gold'+co+a             , c +':Micro Gold'+co+old              
     , c +':Milk Class III'+cm+a         , c2+':Milk Class III'+cm+a         , c +':Milk Class III'+cm+old         , c2+':Milk Class III'+cm+old 
     , c +':Nasdaq-100 Consolidated'+cm+a, c3+':Nasdaq-100 Consolidated'+cm+a, c +':Nasdaq-100 Consolidated'+cm+old   
     , c +':Nasdaq-100 Stock Index'+cm+a , c3+':Nasdaq-100 Stock Index'+cm+a , c +':Nasdaq-100 Stock Index'+cm+old       
     , c +':Natural Gas'+ny+a            , c2+':Natural Gas'+ny+a            , c +':Natural Gas'+ny+old            , c2+':Natural Gas'+ny+old      
     , c +':Non Fat Dry Milk'+cm+a       , c2+':Non Fat Dry Milk'+cm+a       , c +':Non Fat Dry Milk'+cm+old       , c2+':Non Fat Dry Milk'+cm+old 
     , c +':Oats'+cb+a                   , c2+':Oats'+cb+a                   , c +':Oats'+cb+old                   , c2+':Oats'+cb+old              
     , c +':Palladium'+ny+a              , c +':Palladium'+ny+old
     , c +':Platinum'+ny+a               , c2+':Platinum'+ny+a               , c +':Platinum'+ny+old               , c2+':Platinum'+ny+old 
     , c +':Rough Rice'+cb+a             , c2+':Rough Rice'+cb+a             , c +':Rough Rice'+cb+old             , c2+':Rough Rice'+cb+old  
     , c +':Russell 2000 Index'+cm+a     , c3+':Russell 2000 Index'+cm+a     , c +':Russell 2000 Index'+cm+old     
     , c +':Russian Ruble'+cm+a          , c3+':Russian Ruble'+cm+a          , c +':Russian Ruble'+cm+old     
     , c +':S&P 500 Consolidated'+cm+a   , c3+':S&P 500 Consolidated'+cm+a   , c +':S&P 500 Consolidated'+cm+old    
     , c +':S&P 500 Stock Index'+cm+a    , c3+':S&P 500 Stock Index'+cm+a    , c +':S&P 500 Stock Index'+cm+old    
     , c +':Silver'+co+a                 , c2+':Silver'+co+a                 , c +':Silver'+co+old                 , c2+':Silver'+co+old 
     , c +':Soybeans'+cb+a               , c2+':Soybeans'+cb+a               , c +':Soybeans'+cb+old               , c2+':Soybeans'+cb+old  
     , c +':Sugar No. 11'+us+a           , c2+':Sugar No. 11'+us+a           , c +':Sugar No. 11'+us+old           , c2+':Sugar No. 11'+us+old    
     , c +':Swiss Franc'+cm+a            , c3+':Swiss Franc'+cm+a            , c +':Swiss Franc'+cm+old     
     , c +':U.S. Dollar Index'+us+a      , c3+':U.S. Dollar Index'+us+a      , c +':U.S. Dollar Index'+us+old 
     , c +':U.S. Treasury Bonds'+cb+a    , c3+':U.S. Treasury Bonds'+cb+a    , c +':U.S. Treasury Bonds'+cb+old  
     , c +':VIX Futures'+cbo+a           , c3+':VIX Futures'+cbo+a           , c +':VIX Futures'+cbo+old 
     , c +':Wheat HRW'+co+a              , c2+':Wheat HRW'+co+a              , c +':Wheat HRW'+co+old              , c2+':Wheat HRW'+co+old    
     , c +':Wheat HRSPRING'+mg+a         , c2+':Wheat HRSPRING'+mg+a         , c +':Wheat HRSPRING'+mg+old         , c2+':Wheat HRSPRING'+mg+old    
     , c +':Wheat SRW'+co+a              , c2+':Wheat SRW'+co+a              , c +':Wheat SRW'+co+old              , c2+':Wheat SRW'+co+old    
      ]
     )
sm5  = input.symbol    (''                                                   , ''                                  , inline='5', group='Tickers')
res5 = input.timeframe ('D'                                                  , ''                                  , inline='5', group='Tickers')

ac6  = input.bool  (true                                                     , ''                                  , inline='6', group='Tickers')
ch6  = input.string(c +':Russell 2000 Index'+cm+a                            , '6'                                 , inline='6', group='Tickers'
     , options = 
      [ 
       c +':30-Day Federal Funds'+cb+a   , c3+':30-Day Federal Funds'+cb+a   , c +':30-Day Federal Funds'+cb+old
     , c +':1-Month SOFR'+cm+a           , c3+':1-Month SOFR'+cm+a           , c +':1-Month SOFR'+cm+old 
     , c +':3-Month SOFR'+cm+a           , c3+':3-Month SOFR'+cm+a           , c +':3-Month SOFR'+cm+old 
     , c +':Bitcoin'+cm+a                , c3+':Bitcoin'+cm+a                , c +':Bitcoin'+cm+old            
     , c +':Brazilian Real'+cm+a         , c3+':Brazilian Real'+cm+a         , c +':Brazilian Real'+cm+old     
     , c +':Canadian Dollar'+cm+a        , c3+':Canadian Dollar'+cm+a        , c +':Canadian Dollar'+cm+old   
     , c +':Canola'+us+a                 , c2+':Canola'+us+a                 , c +':Canola'+us+old                 , c2+':Canola'+us+old  
     , c +':CME Milk IV'+cm+a            , c2+':CME Milk IV'+cm+a            , c +':CME Milk IV'+cm+old            , c2+':CME Milk IV'+cm+old  
     , c +':Cocoa'+us+a                  , c2+':Cocoa'+us+a                  , c +':Cocoa'+us+old                  , c2+':Cocoa'+us+old  
     , c +':Coffee C'+us+a               , c2+':Coffee C'+us+a               , c +':Coffee C'+us+old               , c2+':Coffee C'+us+old        
     , c +':Corn'+cb+a                   , c2+':Corn'+cb+a                   , c +':Corn'+cb+old                   , c2+':Corn'+cb+old  
     , c +':Cotton No. 2'+us+a           , c2+':Cotton No. 2'+us+a           , c +':Cotton No. 2'+us+old           , c2+':Cotton No. 2'+us+old    
     , c +':Dry Whey'+cm+a               , c2+':Dry Whey'+cm+a               , c +':Dry Whey'+cm+old               , c2+':Dry Whey'+cm+old  
     , c +':Euro FX'+cm+a                , c3+':Euro FX'+cm+a                , c +':Euro FX'+cm+old      
     , c +':Gold'+co+a                   , c +':Gold'+co+old      
     , c +':Japanese Yen'+cm+a           , c3+':Japanese Yen'+cm+a           , c +':Japanese Yen'+cm+old     
     , c +':Lean Hogs'+cm+a              , c2+':Lean Hogs'+cm+a              , c +':Lean Hogs'+cm+old              , c2+':Lean Hogs'+cm+old 
     , c +':Live Cattle'+cm+a            , c2+':Live Cattle'+cm+a            , c +':Live Cattle'+cm+old            , c2+':Live Cattle'+cm+old
     , c +':Mexican Peso'+cm+a           , c3+':Mexican Peso'+cm+a           , c +':Mexican Peso'+cm+old     
     , c +':Micro Bitcoin'+cm+a          , c3+':Micro Bitcoin'+cm+a          , c +':Micro Bitcoin'+cm+old                   
     , c +':Micro Gold'+co+a             , c +':Micro Gold'+co+old              
     , c +':Milk Class III'+cm+a         , c2+':Milk Class III'+cm+a         , c +':Milk Class III'+cm+old         , c2+':Milk Class III'+cm+old 
     , c +':Nasdaq-100 Consolidated'+cm+a, c3+':Nasdaq-100 Consolidated'+cm+a, c +':Nasdaq-100 Consolidated'+cm+old   
     , c +':Nasdaq-100 Stock Index'+cm+a , c3+':Nasdaq-100 Stock Index'+cm+a , c +':Nasdaq-100 Stock Index'+cm+old       
     , c +':Natural Gas'+ny+a            , c2+':Natural Gas'+ny+a            , c +':Natural Gas'+ny+old            , c2+':Natural Gas'+ny+old      
     , c +':Non Fat Dry Milk'+cm+a       , c2+':Non Fat Dry Milk'+cm+a       , c +':Non Fat Dry Milk'+cm+old       , c2+':Non Fat Dry Milk'+cm+old 
     , c +':Oats'+cb+a                   , c2+':Oats'+cb+a                   , c +':Oats'+cb+old                   , c2+':Oats'+cb+old              
     , c +':Palladium'+ny+a              , c +':Palladium'+ny+old
     , c +':Platinum'+ny+a               , c2+':Platinum'+ny+a               , c +':Platinum'+ny+old               , c2+':Platinum'+ny+old 
     , c +':Rough Rice'+cb+a             , c2+':Rough Rice'+cb+a             , c +':Rough Rice'+cb+old             , c2+':Rough Rice'+cb+old  
     , c +':Russell 2000 Index'+cm+a     , c3+':Russell 2000 Index'+cm+a     , c +':Russell 2000 Index'+cm+old     
     , c +':Russian Ruble'+cm+a          , c3+':Russian Ruble'+cm+a          , c +':Russian Ruble'+cm+old     
     , c +':S&P 500 Consolidated'+cm+a   , c3+':S&P 500 Consolidated'+cm+a   , c +':S&P 500 Consolidated'+cm+old    
     , c +':S&P 500 Stock Index'+cm+a    , c3+':S&P 500 Stock Index'+cm+a    , c +':S&P 500 Stock Index'+cm+old    
     , c +':Silver'+co+a                 , c2+':Silver'+co+a                 , c +':Silver'+co+old                 , c2+':Silver'+co+old 
     , c +':Soybeans'+cb+a               , c2+':Soybeans'+cb+a               , c +':Soybeans'+cb+old               , c2+':Soybeans'+cb+old  
     , c +':Sugar No. 11'+us+a           , c2+':Sugar No. 11'+us+a           , c +':Sugar No. 11'+us+old           , c2+':Sugar No. 11'+us+old    
     , c +':Swiss Franc'+cm+a            , c3+':Swiss Franc'+cm+a            , c +':Swiss Franc'+cm+old     
     , c +':U.S. Dollar Index'+us+a      , c3+':U.S. Dollar Index'+us+a      , c +':U.S. Dollar Index'+us+old 
     , c +':U.S. Treasury Bonds'+cb+a    , c3+':U.S. Treasury Bonds'+cb+a    , c +':U.S. Treasury Bonds'+cb+old  
     , c +':VIX Futures'+cbo+a           , c3+':VIX Futures'+cbo+a           , c +':VIX Futures'+cbo+old 
     , c +':Wheat HRW'+co+a              , c2+':Wheat HRW'+co+a              , c +':Wheat HRW'+co+old              , c2+':Wheat HRW'+co+old    
     , c +':Wheat HRSPRING'+mg+a         , c2+':Wheat HRSPRING'+mg+a         , c +':Wheat HRSPRING'+mg+old         , c2+':Wheat HRSPRING'+mg+old    
     , c +':Wheat SRW'+co+a              , c2+':Wheat SRW'+co+a              , c +':Wheat SRW'+co+old              , c2+':Wheat SRW'+co+old    
      ]
     )
sm6  = input.symbol    (''                                                   , ''                                  , inline='6', group='Tickers')
res6 = input.timeframe ('D'                                                  , ''                                  , inline='6', group='Tickers')

sw   = input.bool      (true        , '          from middle   '                   , group='style', tooltip='plots from:\n• middle line\n• center of circle'             )
sz_  = input.string    ('normal'    , 'size'                                       , group='style', tooltip='Size circle',options=['tiny','small','normal','large','huge']) 

ang  = input.float     (  1.        , 'angle'    , minval= 0, maxval=  2, step=0.05, group='style', tooltip='When "From middle" is disabled:\n• Sets the angle of shapes')
addT = input.bool      (false       , '           Show Ticker   '                  , group='style', tooltip='Show Ticker on label'                                       )
cTx1 = input.color     (#10be37   ,   '+'      ,            inline='1'           , group='      text   -   fill'                                                       )
cTx5 = input.color     (#f23645   ,   '- '     ,            inline='5'           , group='      text   -   fill'                                                       ) 
col1 = input.color     (#10be3787 ,    ''      ,            inline='1'           , group='      text   -   fill' , tooltip='colour positive percentage'                ) 
col5 = input.color     (#f236457c ,    ''      ,            inline='5'           , group='      text   -   fill' , tooltip='colour negative percentage'                )
txt1 = input.color     (#04c3c3   ,  '   '     ,            inline='2'           , group='      table'                                                                 )
txt2 = input.color     (#d40ecee5 ,    ''      ,            inline='2'           , group='      table'           , tooltip='table colours text'                        )    

tSz  = input.string    (size.small, 'size', options=[size.tiny, size.small, size.normal, size.large])
tPos = input.string    (position.top_right, 'position', options=
 [ position.top_left   , position.top_center   , position.top_right
 , position.middle_left, position.middle_center, position.middle_right
 , position.bottom_left, position.bottom_center, position.bottom_right
 ]
 )

cP0  = input.color     (color.new(color.aqua  , 25), title='Edge'                , group='      circles')
cP1  = input.color     (color.new(color.silver, 95), title='circle 1'            , group='      circles')
cP2  = input.color     (color.new(color.aqua  , 75), title='circle 2'            , group='      circles')
cP3  = input.color     (color.new(color.aqua  , 25), title='circle 3'            , group='      circles')
cP4  = input.color     (color.new(color.aqua  , 75), title='circle 4'            , group='      circles')

//-----------------------------------------------------------------------------}
//General Calculations
//-----------------------------------------------------------------------------{
cC          = chart.fg_color
n           = bar_index
lbi         = last_bar_index
barsTillEnd = lbi - n 
change      = ((close / close[1]) - 1) * 100
sz1         = switch sz_ 
    'tiny'  => 44 
    'small' => 64 
    'normal'=> 80 
    'large' => 101 
    'huge'  => 152 

//-----------------------------------------------------------------------------}
//UDT's
//-----------------------------------------------------------------------------{
type val
    int   x 
    float h
    float l

type values 
    val[] _1
    val[] _2
    val[] _3
    val[] _4

var values values = 
 values.new(
   array.new<val>()
 , array.new<val>()
 , array.new<val>()
 , array.new<val>()
 )

//-----------------------------------------------------------------------------}
//Functions
//-----------------------------------------------------------------------------{
// % rise/fall of _OI futures/tickers
set(n, i) => 
    max  = math.ceil(n / i) * i
    part = max / i
    [max, part]

createOuterCircle(radius) => 
    var int end   = na
    var int start = na
    var basis     = 0.
    barsFromNearestEdgeCircle   = 0.
    barsTillEndFromCircleStart  = radius
    startCylce                  = barsTillEnd % barsTillEndFromCircleStart == 0            // start circle    
    bars                        = ta.barssince(startCylce)                                                              
    barsFromNearestEdgeCircle  := barsTillEndFromCircleStart -1 

    basis   := math.min(startCylce ? -1 : basis + 1 / barsFromNearestEdgeCircle * 2, 1)    // 0 -> 1                    
    shape    = math.sqrt(1 - basis * basis) 
    rad      =      radius     /  2
    isOK     = barsTillEnd <= barsTillEndFromCircleStart and  barsTillEnd >  0
    hi       = isOK ? (rad + shape * radius) - rad : na
    lo       = isOK ? (rad - shape * radius) - rad : na
    start   := barsTillEnd     == barsTillEndFromCircleStart ? n -1 : start
    end     := barsTillEnd     == 0  ? start + radius : end // n -1 : end
    if isOK
        values._1.unshift(val.new(n, hi, lo))

    [hi, lo, start +1, end]

[hi1, lo1, start1, end1] = createOuterCircle(sz1)

createInnerCircle(num, e) => 
    piece = math.round(sz1 / e)
    start = start1 + piece
    end   = start1 + sz1 - piece
    var basis                  = 0.
    barsFromNearestEdgeCircle  = 0.
    barsTillEndFromCirclesEnd  = piece
    barsTillEndFromCircleStart = sz1 - piece * 2
    startCylce                 = (barsTillEnd - piece) % (barsTillEndFromCircleStart) == 0                              
    bars                       = ta.barssince(startCylce)                                                               
    barsFromNearestEdgeCircle := barsTillEndFromCircleStart -1                                                          
    basis   := math.min(startCylce ? -1 : basis + 1 / barsFromNearestEdgeCircle * 2, 1)
    shape    = math.sqrt(1 - basis * basis)
    rad      =         sz1    /  2
    isOK     = barsTillEnd    <= (barsTillEndFromCircleStart + piece) and 
               barsTillEnd    >   barsTillEndFromCirclesEnd 
    hi       = isOK  ? (rad + shape * barsTillEndFromCircleStart) - rad : na
    lo       = isOK  ? (rad - shape * barsTillEndFromCircleStart) - rad : na
    if isOK
        switch num
            2 => values._2.unshift(val.new(n, hi, lo))
            3 => values._3.unshift(val.new(n, hi, lo))
            4 => values._4.unshift(val.new(n, hi, lo))

    [hi, lo, start, end]

c(val, o) =>
    cl    = color(na)
    cl   := switch 
        val >  0 => (o == 't' ? cTx1 : col1)
        val <  0 => (o == 't' ? cTx5 : col5) 
        val == 0 => color.blue
        =>          color.gray
        
lab() => 
    label.new(
       na
     , na
     , style=label.style_label_center
     , textcolor=color.rgb(223, 51, 253)
     , color=color(na)
     , size=size.tiny
     , text='●')

f_lb() =>
    label.new( 
     na, na, color= color.new(color.silver, 85)
     , textcolor= color.fuchsia
     , size = size.small
     )

units() => 
    label.new(
     na, na
     , style=label.style_label_center
     , color=color(na), textcolor=cC)

f_ln(i) => 
    line.new(
       na, na
     , na, na
     , style=line.style_dotted
     , color=color.new(color.silver, i))

f_lf() => 
    linefill.new(
         line.new(na, na, na, na, color=color.new(cC, 50))
       , line.new(na, na, na, na, color=color.new(cC, 50))
       , color(na))

tab(tab, t, p, d, v, i) => 
    col  = i % 2 == 0 ? color.new(color.gray, 90) : color.new(color.silver, 90)
    colt = i % 2 == 0 ? color.new(#b027a9   ,  0) : color.new(color.aqua  ,  0)
    colv = c(v, 't'), _v = str.tostring(math.round(v, 2))  
    table.cell(tab, 0, i, text = t, bgcolor = col, text_color=cC  , text_size=tSz)
    table.cell(tab, 1, i, text = p, bgcolor = col, text_color=colt, text_size=tSz)
    table.cell(tab, 2, i, text = d, bgcolor = col, text_color=colt, text_size=tSz)
    table.cell(tab, 3, i, text =_v, bgcolor = col, text_color=colv, text_size=tSz)

f_str(i, val, res, des) => 
    r   = res != '' ? '\n(TF: ' + res + ')' : ''
    d   = addT ? '\n' + des : ''
    out = str.format("{0}{1}\n{2}{3}", i, d, math.round(val, 2), r) 

//-----------------------------------------------------------------------------}
//Methods
//-----------------------------------------------------------------------------{
method style(label lb, val, neg, pos) => lb.set_style(val > 0 or not sw ? pos : neg)

method replace(string s) => str.replace_all(str.replace_all(s, "Futures",  "F"), 'Open Interest', 'OI')

method pick(simple string ch) => 
    p = '', t = ''
    switch ch

        c +':30-Day Federal Funds'+cb+a     => p := c , t := '045601'+f
        c3+':30-Day Federal Funds'+cb+a     => p := c3, t := '045601'+f
        c +':30-Day Federal Funds'+cb+old   => p := c , t := '045601'+fold

        c +':1-Month SOFR'+cm+a             => p := c , t := '134742'+f
        c3+':1-Month SOFR'+cm+a             => p := c3, t := '134742'+f
        c +':1-Month SOFR'+cm+old           => p := c , t := '134742'+fold

        c +':3-Month SOFR'+cm+a             => p := c , t := '134741'+f
        c3+':3-Month SOFR'+cm+a             => p := c3, t := '134741'+f
        c +':3-Month SOFR'+cm+old           => p := c , t := '134741'+fold

        c +':Bitcoin'+cm+a                  => p := c , t := '133741'+f 
        c3+':Bitcoin'+cm+a                  => p := c3, t := '133741'+f 
        c +':Bitcoin'+cm+old                => p := c , t := '133741'+fold 

        c +':Brazilian Real'+cm+a           => p := c , t := '102741'+f 
        c3+':Brazilian Real'+cm+a           => p := c3, t := '102741'+f 
        c +':Brazilian Real'+cm+old         => p := c , t := '102741'+fold      

        c +':Coffee C'+us+a                 => p := c , t := '083731'+f 
        c2+':Coffee C'+us+a                 => p := c2, t := '083731'+f 
        c +':Coffee C'+us+old               => p := c , t := '083731'+fold
        c2+':Coffee C'+us+old               => p := c2, t := '083731'+fold

        c +':Canadian Dollar'+cm+a          => p := c , t := '090741'+f 
        c3+':Canadian Dollar'+cm+a          => p := c3, t := '090741'+f 
        c +':Canadian Dollar'+cm+old        => p := c , t := '090741'+fold

        c +':Canola'+us+a                   => p := c , t := '135731'+f
        c2+':Canola'+us+a                   => p := c2, t := '135731'+f
        c +':Canola'+us+old                 => p := c , t := '135731'+fold
        c2+':Canola'+us+old                 => p := c2, t := '135731'+fold 

        c +':CME Milk IV'+cm+a              => p := c , t := '052644'+f 
        c2+':CME Milk IV'+cm+a              => p := c2, t := '052644'+f 
        c +':CME Milk IV'+cm+old            => p := c , t := '052644'+fold
        c2+':CME Milk IV'+cm+old            => p := c2, t := '052644'+fold  

        c +':Cocoa'+us+a                    => p := c , t := '073732'+f
        c2+':Cocoa'+us+a                    => p := c2, t := '073732'+f
        c +':Cocoa'+us+old                  => p := c , t := '073732'+fold
        c2+':Cocoa'+us+old                  => p := c2, t := '073732'+fold

        c +':Corn'+cb+a                     => p := c , t := '002602'+f
        c2+':Corn'+cb+a                     => p := c2, t := '002602'+f 
        c +':Corn'+cb+old                   => p := c , t := '002602'+fold
        c2+':Corn'+cb+old                   => p := c2, t := '002602'+fold

        c +':Cotton No. 2'+us+a             => p := c , t := '033661'+f 
        c2+':Cotton No. 2'+us+a             => p := c2, t := '033661'+f 
        c +':Cotton No. 2'+us+old           => p := c , t := '033661'+fold 
        c2+':Cotton No. 2'+us+old           => p := c2, t := '033661'+fold        

        c +':Dry Whey'+cm+a                 => p := c , t := '052645'+f
        c2+':Dry Whey'+cm+a                 => p := c , t := '052645'+f
        c +':Dry Whey'+cm+old               => p := c , t := '052645'+fold
        c2+':Dry Whey'+cm+old               => p := c , t := '052645'+fold 

        c +':Euro FX'+cm+a                  => p := c , t := '099741'+f  
        c3+':Euro FX'+cm+a                  => p := c3, t := '099741'+f
        c +':Euro FX'+cm+old                => p := c , t := '099741'+fold

        c +':Gold'+co+a                     => p := c , t := '088691'+f 
        c +':Gold'+co+old                   => p := c , t := '088691'+fold 

        c +':Japanese Yen'+cm+a             => p := c , t := '097741'+f 
        c3+':Japanese Yen'+cm+a             => p := c3, t := '097741'+f 
        c +':Japanese Yen'+cm+old           => p := c , t := '097741'+fold 

        c +':Lean Hogs'+cm+a                => p := c , t := '054642'+f 
        c2+':Lean Hogs'+cm+a                => p := c2, t := '054642'+f 
        c +':Lean Hogs'+cm+old              => p := c , t := '054642'+fold 
        c2+':Lean Hogs'+cm+old              => p := c2, t := '054642'+fold 

        c +':Live Cattle'+cm+a              => p := c , t := '057642'+f 
        c2+':Live Cattle'+cm+a              => p := c2, t := '057642'+f 
        c +':Live Cattle'+cm+old            => p := c , t := '057642'+fold 
        c2+':Live Cattle'+cm+old            => p := c2, t := '057642'+fold  

        c +':Mexican Peso'+cm+a             => p := c , t := '095741'+f 
        c3+':Mexican Peso'+cm+a             => p := c3, t := '095741'+f 
        c +':Mexican Peso'+cm+old           => p := c , t := '095741'+fold  

        c +':Micro Bitcoin'+cm+a            => p := c , t := '133742'+f 
        c3+':Micro Bitcoin'+cm+a            => p := c3, t := '133742'+f 
        c +':Micro Bitcoin'+cm+old          => p := c , t := '133742'+fold 

        c +':Micro Gold'+co+a               => p := c , t := '088695'+f 
        c +':Micro Gold'+co+old             => p := c , t := '088695'+fold 

        c +':Milk Class III'+cm+a           => p := c , t := '052641'+f
        c2+':Milk Class III'+cm+a           => p := c2, t := '052641'+f
        c +':Milk Class III'+cm+old         => p := c , t := '052641'+fold
        c2+':Milk Class III'+cm+old         => p := c2, t := '052641'+fold

        c +':Nasdaq-100 Consolidated'+cm+a  => p := c , t := '20974+'+f
        c3+':Nasdaq-100 Consolidated'+cm+a  => p := c3, t := '20974+'+f
        c +':Nasdaq-100 Consolidated'+cm+old=> p := c , t := '20974+'+fold  

        c +':Nasdaq-100 Stock Index'+cm+a   => p := c , t := '209742'+f
        c3+':Nasdaq-100 Stock Index'+cm+a   => p := c3, t := '209742'+f
        c +':Nasdaq-100 Stock Index'+cm+old => p := c , t := '209742'+fold 

        c +':Natural Gas'+ny+a              => p := c , t := '023651'+f
        c2+':Natural Gas'+ny+a              => p := c2, t := '023651'+f
        c +':Natural Gas'+ny+old            => p := c , t := '023651'+fold
        c2+':Natural Gas'+ny+old            => p := c2, t := '023651'+fold

        c +':Non Fat Dry Milk'+cm+a         => p := c , t := '052642'+f
        c2+':Non Fat Dry Milk'+cm+a         => p := c2, t := '052642'+f
        c +':Non Fat Dry Milk'+cm+old       => p := c , t := '052642'+fold
        c2+':Non Fat Dry Milk'+cm+old       => p := c2, t := '052642'+fold 

        c +':Oats'+cb+a                     => p := c , t := '004603'+f
        c2+':Oats'+cb+a                     => p := c2, t := '004603'+f 
        c +':Oats'+cb+old                   => p := c , t := '004603'+fold
        c2+':Oats'+cb+old                   => p := c2, t := '004603'+fold

        c +':Palladium'+ny+a                => p := c , t := '075651'+f
        c +':Palladium'+ny+old              => p := c , t := '075651'+fold

        c +':Platinum'+ny+a                 => p := c , t := '076651'+f
        c2+':Platinum'+ny+a                 => p := c2, t := '076651'+f 
        c +':Platinum'+ny+old               => p := c , t := '076651'+fold  
        c2+':Platinum'+ny+old               => p := c2, t := '076651'+fold

        c +':Rough Rice'+cb+a               => p := c , t := '039601'+f
        c2+':Rough Rice'+cb+a               => p := c2, t := '039601'+f
        c +':Rough Rice'+cb+old             => p := c , t := '039601'+fold
        c2+':Rough Rice'+cb+old             => p := c2, t := '039601'+fold     

        c +':Russell 2000 Index'+cm+a       => p := c , t := '239742'+f
        c3+':Russell 2000 Index'+cm+a       => p := c3, t := '239742'+f
        c +':Russell 2000 Index'+cm+old     => p := c , t := '239742'+fold

        c +':Russian Ruble'+cm+a            => p := c , t := '089741'+f 
        c3+':Russian Ruble'+cm+a            => p := c3, t := '089741'+f 
        c +':Russian Ruble'+cm+old          => p := c , t := '089741'+fold      

        c +':S&P 500 Consolidated'+cm+a     => p := c , t := '13874+'+f 
        c3+':S&P 500 Consolidated'+cm+a     => p := c3, t := '13874+'+f 
        c +':S&P 500 Consolidated'+cm+old   => p := c , t := '13874+'+fold   

        c +':S&P 500 Stock Index'+cm+a      => p := c , t := '138741'+f 
        c3+':S&P 500 Stock Index'+cm+a      => p := c3, t := '138741'+f 
        c +':S&P 500 Stock Index'+cm+old    => p := c , t := '138741'+fold  

        c +':Silver'+co+a                   => p := c , t := '084691'+f
        c2+':Silver'+co+a                   => p := c2, t := '084691'+f
        c +':Silver'+co+old                 => p := c , t := '084691'+fold
        c2+':Silver'+co+old                 => p := c2, t := '084691'+fold 

        c +':Soybeans'+cb+a                 => p := c , t := '005602'+f
        c2+':Soybeans'+cb+a                 => p := c2, t := '005602'+f
        c +':Soybeans'+cb+old               => p := c , t := '005602'+fold
        c2+':Soybeans'+cb+old               => p := c2, t := '005602'+fold

        c +':Sugar No. 11'+us+a             => p := c , t := '080732'+f
        c2+':Sugar No. 11'+us+a             => p := c2, t := '080732'+f
        c +':Sugar No. 11'+us+old           => p := c , t := '080732'+fold
        c2+':Sugar No. 11'+us+old           => p := c2, t := '080732'+fold

        c +':Swiss Franc'+cm+a              => p := c , t := '092741'+f 
        c3+':Swiss Franc'+cm+a              => p := c3, t := '092741'+f 
        c +':Swiss Franc'+cm+old            => p := c , t := '092741'+fold 

        c +':U.S. Dollar Index'+us+a        => p := c , t := '098662'+f
        c3+':U.S. Dollar Index'+us+a        => p := c3, t := '098662'+f
        c +':U.S. Dollar Index'+us+old      => p := c , t := '098662'+fold

        c +':U.S. Treasury Bonds'+cb+a      => p := c , t := '020601'+f
        c3+':U.S. Treasury Bonds'+cb+a      => p := c3, t := '020601'+f
        c +':U.S. Treasury Bonds'+cb+old    => p := c , t := '020601'+fold

        c +':VIX Futures'+cbo+a             => p := c , t := '1170E1'+f 
        c3+':VIX Futures'+cbo+a             => p := c3, t := '1170E1'+f 
        c +':VIX Futures'+cbo+old           => p := c , t := '1170E1'+fold

        c +':Wheat SRW'+co+a                => p := c , t := '001602'+f
        c2+':Wheat SRW'+co+a                => p := c2, t := '001602'+f
        c +':Wheat SRW'+co+old              => p := c , t := '001602'+fold
        c2+':Wheat SRW'+co+old              => p := c2, t := '001602'+fold  

        c +':Wheat HRW'+co+a                => p := c , t := '001612'+f
        c2+':Wheat HRW'+co+a                => p := c2, t := '001612'+f
        c +':Wheat HRW'+co+old              => p := c , t := '001612'+fold
        c2+':Wheat HRW'+co+old              => p := c2, t := '001612'+fold  

        c +':Wheat HRSPRING'+mg+a           => p := c , t := '001626'+f
        c2+':Wheat HRSPRING'+mg+a           => p := c2, t := '001626'+f
        c +':Wheat HRSPRING'+mg+old         => p := c , t := '001626'+fold
        c2+':Wheat HRSPRING'+mg+old         => p := c2, t := '001626'+fold  

    [p, t]

//-----------------------------------------------------------------------------}
//Variables
//-----------------------------------------------------------------------------{
var line ln1 = f_ln(75), var line l_1 = f_ln(15), var label lb1 = lab(), var label tx1 = f_lb(), var label un1 = units()
var line ln2 = f_ln(75), var line l_2 = f_ln(15), var label lb2 = lab(), var label tx2 = f_lb(), var label un2 = units()
var line ln3 = f_ln(75), var line l_3 = f_ln(15), var label lb3 = lab(), var label tx3 = f_lb(), var label un3 = units()
var line ln4 = f_ln(75), var line l_4 = f_ln(15), var label lb4 = lab(), var label tx4 = f_lb(), var label un4 = units()
var line ln5 = f_ln(75), var line l_5 = f_ln(15), var label lb5 = lab(), var label tx5 = f_lb(), var label un5 = units()
var line ln6 = f_ln(75), var line l_6 = f_ln(15), var label lb6 = lab(), var label tx6 = f_lb(), var label un6 = units()


var linefill lf1 = f_lf(), var linefill lf5 = f_lf(), var linefill lf9  = f_lf ()
var linefill lf2 = f_lf(), var linefill lf6 = f_lf(), var linefill lf10 = f_lf ()
var linefill lf3 = f_lf(), var linefill lf7 = f_lf(), var linefill lf11 = f_lf ()
var linefill lf4 = f_lf(), var linefill lf8 = f_lf(), var linefill lf12 = f_lf ()

//-----------------------------------------------------------------------------}
//Calculations
//-----------------------------------------------------------------------------{
[hi2, lo2, start2, end2] = createInnerCircle(2, sz1 / (sz1 * 0.105))
[hi3, lo3, start3, end3] = createInnerCircle(3, sz1 / (sz1 * 0.25 ))
[hi4, lo4, start4, end4] = createInnerCircle(4, sz1 / (sz1 * 0.375))

[p1, t1] = ch1.pick(), sym1 = ac1 ? ticker.new(p1, t1) : sm1      
[p2, t2] = ch2.pick(), sym2 = ac2 ? ticker.new(p2, t2) : sm2        
[p3, t3] = ch3.pick(), sym3 = ac3 ? ticker.new(p3, t3) : sm3        
[p4, t4] = ch4.pick(), sym4 = ac4 ? ticker.new(p4, t4) : sm4        
[p5, t5] = ch5.pick(), sym5 = ac5 ? ticker.new(p5, t5) : sm5        
[p6, t6] = ch6.pick(), sym6 = ac6 ? ticker.new(p6, t6) : sm6        


[val1, pre1, des1] = request.security(sym1, res1, [change, syminfo.prefix, syminfo.description], ignore_invalid_symbol = true)
[val2, pre2, des2] = request.security(sym2, res2, [change, syminfo.prefix, syminfo.description], ignore_invalid_symbol = true)
[val3, pre3, des3] = request.security(sym3, res3, [change, syminfo.prefix, syminfo.description], ignore_invalid_symbol = true)
[val4, pre4, des4] = request.security(sym4, res4, [change, syminfo.prefix, syminfo.description], ignore_invalid_symbol = true)
[val5, pre5, des5] = request.security(sym5, res5, [change, syminfo.prefix, syminfo.description], ignore_invalid_symbol = true)
[val6, pre6, des6] = request.security(sym6, res6, [change, syminfo.prefix, syminfo.description], ignore_invalid_symbol = true)

naV1   = val1, val1  := nz(val1)
naV2   = val2, val2  := nz(val2)
naV3   = val3, val3  := nz(val3)
naV4   = val4, val4  := nz(val4)
naV5   = val5, val5  := nz(val5)
naV6   = val6, val6  := nz(val6)

max    = math.max(math.abs(val1), math.abs(val2), math.abs(val3), math.abs(val4), math.abs(val5), math.abs(val6))

[m, p] = set(max, 1) // input.float(0.5, '', step=0.5))

if ta.change(chart.left_visible_bar_time ) or
   ta.change(chart.right_visible_bar_time) 
    n := bar_index

//-----------------------------------------------------------------------------}
//Execution
//-----------------------------------------------------------------------------{
if barstate.islast and lbi - n < 500

    size_1 = values._1.size()
    size_3 = values._3.size()

    deg0_1_get     = values._1.get(math.round(size_1 * .5  ))
    deg30_1_get    = values._1.get(math.round(size_1 * .275))
    deg60_1_get    = values._1.get(math.round(size_1 * .1  ))
    deg210_1_get   = values._1.get(math.round(size_1 * .725))
    deg240_1_get   = values._1.get(math.round(size_1 * .9  ))
    deg270_1_get   = values._1.get(           size_1   -1   )

    deg0_3_get     = values._3.get(math.round(size_3 * .5  ))
    deg30_3_get    = values._3.get(math.round(size_3 * .275))
    deg60_3_get    = values._3.get(math.round(size_3 * .1  ))
    deg210_3_get   = values._3.get(math.round(size_3 * .725))
    deg240_3_get   = values._3.get(math.round(size_3 * .9  ))
    deg270_3_get   = values._3.get(           size_3   -1   )

    // Circle 1 (largest)
    deg0_1_x    = deg0_1_get.x  , deg0_1_h    = deg0_1_get.h  , deg0_1_l   = deg0_1_get.l       //   0°  - 180° 
    deg30_1_x   = deg30_1_get.x , deg30_1_h   = deg30_1_get.h , deg30_1_l  = deg30_1_get.l      //  30°  - 150° 
    deg60_1_x   = deg60_1_get.x , deg60_1_h   = deg60_1_get.h , deg60_1_l  = deg60_1_get.l      //  60°  - 120° 
    deg90_1_x   = end1          , deg90_1_h   = 0                                               //  90°
    deg210_1_x  = deg210_1_get.x, deg210_1_h  = deg210_1_get.h, deg210_1_l = deg210_1_get.l     // 210°  - 330°
    deg240_1_x  = deg240_1_get.x, deg240_1_h  = deg240_1_get.h, deg240_1_l = deg240_1_get.l     // 240°  - 300° 
    deg270_1_x  = deg270_1_get.x, deg270_1_h  = 0                                               // 270°

    // Circle 3 (Mid)
    deg0_3_x    = deg0_3_get.x  , deg0_3_h    = deg0_3_get.h  , deg0_3_l   = deg0_3_get.l       //   0°  - 180° 
    deg30_3_x   = deg30_3_get.x , deg30_3_h   = deg30_3_get.h , deg30_3_l  = deg30_3_get.l      //  30°  - 150° 
    deg60_3_x   = deg60_3_get.x , deg60_3_h   = deg60_3_get.h , deg60_3_l  = deg60_3_get.l      //  60°  - 120° 
    deg90_3_x   = end3 -1       , deg90_3_h   = 0                                               //  90°
    deg210_3_x  = deg210_3_get.x, deg210_3_h  = deg210_3_get.h, deg210_3_l = deg210_3_get.l     // 210°  - 330°
    deg240_3_x  = deg240_3_get.x, deg240_3_h  = deg240_3_get.h, deg240_3_l = deg240_3_get.l     // 240°  - 300° 
    deg270_3_x  = deg270_3_get.x, deg270_3_h  = 0                                               // 270°

    // axis lines
    l_1.set_xy1(deg0_1_x, 0), l_1.set_xy2(deg0_1_x  ,  deg0_1_h ) //   0°
    ln1.set_xy1(deg0_1_x, 0), ln1.set_xy2(deg30_1_x , deg30_1_h ) //  30°
    l_2.set_xy1(deg0_1_x, 0), l_2.set_xy2(deg60_1_x , deg60_1_h ) //  60°
    ln2.set_xy1(deg0_1_x, 0), ln2.set_xy2(deg90_1_x , deg90_1_h ) //  90°
    l_3.set_xy1(deg0_1_x, 0), l_3.set_xy2(deg60_1_x , deg60_1_l ) // 120°
    ln3.set_xy1(deg0_1_x, 0), ln3.set_xy2(deg30_1_x , deg30_1_l ) // 150°
    l_4.set_xy1(deg0_1_x, 0), l_4.set_xy2(deg0_1_x  ,  deg0_1_l ) // 180°
    ln4.set_xy1(deg0_1_x, 0), ln4.set_xy2(deg210_1_x, deg210_1_l) // 210°
    l_5.set_xy1(deg0_1_x, 0), l_5.set_xy2(deg240_1_x, deg240_1_l) // 240°
    ln5.set_xy1(deg0_1_x, 0), ln5.set_xy2(deg270_1_x,         0 ) // 270°
    l_6.set_xy1(deg0_1_x, 0), l_6.set_xy2(deg240_1_x, deg240_1_h) // 300°
    ln6.set_xy1(deg0_1_x, 0), ln6.set_xy2(deg210_1_x, deg210_1_h) // 330°

    // text labels
    tx1.set_xy(deg30_1_x , deg30_1_h ), tx1.set_textcolor(c(naV1, 't')), tx1.set_text(f_str(1, naV1, res1, des1.replace())), tx1.set_style(label.style_label_lower_left )    
    tx2.set_xy(deg90_1_x , deg90_1_h ), tx2.set_textcolor(c(naV2, 't')), tx2.set_text(f_str(2, naV2, res2, des2.replace())), tx2.set_style(label.style_label_left       ) 
    tx3.set_xy(deg30_1_x , deg30_1_l ), tx3.set_textcolor(c(naV3, 't')), tx3.set_text(f_str(3, naV3, res3, des3.replace())), tx3.set_style(label.style_label_upper_left ) 
    tx4.set_xy(deg210_1_x, deg210_1_l), tx4.set_textcolor(c(naV4, 't')), tx4.set_text(f_str(4, naV4, res4, des4.replace())), tx4.set_style(label.style_label_upper_right) 
    tx5.set_xy(deg270_1_x,         0 ), tx5.set_textcolor(c(naV5, 't')), tx5.set_text(f_str(5, naV5, res5, des5.replace())), tx5.set_style(label.style_label_right      ) 
    tx6.set_xy(deg210_1_x, deg210_1_h), tx6.set_textcolor(c(naV6, 't')), tx6.set_text(f_str(6, naV6, res6, des6.replace())), tx6.set_style(label.style_label_lower_right) 
    
    xMid30  = sw ? math.round(math.avg(deg0_1_x, deg30_1_x))  : deg0_1_x
    yMid30  = sw ? deg30_3_h  : 0
    xMid90  = sw ? end3 -1    : deg0_1_x
    yMid90  =    0
    xMid150 = sw ? xMid30     : deg0_1_x
    yMid150 = sw ? deg30_3_l  : 0
    xMid210 = sw ? math.round(math.avg(deg0_1_x, deg210_1_x)) : deg0_1_x
    yMid210 = sw ? deg210_3_l : 0
    xMid270 = sw ? start3     : deg0_1_x
    yMid270 =    0
    xMid330 = sw ? xMid210    : deg0_1_x
    yMid330 = sw ? deg210_3_h : 0

    A1x1 = deg0_1_x                                                                                                     // Lside 1
    A1y1 = sw ? deg0_3_h  :                                       deg0_3_h * (math.abs(val1 * ang) / m)                 // Lside 1
    A1x2 = sw ? xMid30    :                                       deg0_1_x  
    A1y2 = sw ? yMid30    : 0 
    A2x1 = A1x1    
    A2y1 = A1y1
    A2x2 = 
      sw ? math.round(deg30_3_x + (deg30_1_x - deg30_3_x) * (val1 / m))
         : math.round(deg0_1_x  + (deg30_1_x - deg0_1_x ) * (math.abs(val1) / m))                                       // POINT 1
    A2y2 = ln1.get_price(A2x2)                                                                                          // POINT 1

    B1x1 = sw ? deg60_3_x : math.round(deg0_1_x + ((deg60_1_x - deg60_3_x) * (math.abs(val1 * ang) / m)))               // Rside 1
    B1y1 = l_2.get_price(B1x1)                                                                                          // Rside 1
    B1x2 = A1x2 
    B1y2 = A1y2
    B2x1 = B1x1    
    B2y1 = B1y1
    B2x2 = A2x2    
    B2y2 = A2y2 

    C1x1 = sw ? deg60_3_x : math.round(deg0_1_x + ((deg60_1_x - deg60_3_x) * (math.abs(val2 * ang) / m)))               // Lside 2
    C1y1 = l_2.get_price(C1x1)                                                                                          // Lside 2
    C1x2 = sw ? xMid90    : deg0_1_x  
    C1y2 = sw ? yMid90    : 0  
    C2x1 = C1x1    
    C2y1 = C1y1
    C2x2 = 
      sw ? math.round(deg90_3_x + ( (n -1)   - deg90_3_x) * (val2 / m))
         : math.round(deg0_1_x  + (deg90_1_x - deg0_1_x ) * (math.abs(val2) / m))                                       // POINT 2
    C2y2 = 0                                                                                               //    90°    // POINT 2

    D1x1 = sw ? deg60_3_x : math.round(deg0_1_x + ((deg60_1_x - deg60_3_x) * (math.abs(val2 * ang) / m)))               // Rside 2
    D1y1 = l_3.get_price(D1x1)                                                                                          // Rside 2
    D1x2 = C1x2 
    D1y2 = C1y2
    D2x1 = D1x1    
    D2y1 = D1y1
    D2x2 = C2x2    
    D2y2 = C2y2 

    E1x1 = sw ? deg60_3_x : math.round(deg0_1_x + ((deg60_1_x - deg60_3_x) * (math.abs(val3 * ang) / m)))               // Lside 3
    E1y1 = l_3.get_price(E1x1)                                                                                          // Lside 3
    E1x2 = sw ? xMid150   : deg0_1_x  
    E1y2 = sw ? yMid150   : 0 
    E2x1 = E1x1    
    E2y1 = E1y1
    E2x2 = 
      sw ? math.round(deg30_3_x + (deg30_1_x - deg30_3_x) * (val3 / m))
         : math.round(deg0_1_x  + (deg30_1_x - deg0_1_x ) * (math.abs(val3) / m))                                       // POINT 3    
    E2y2 = ln3.get_price(E2x2)                                                                                          // POINT 3

    F1x1 = deg0_1_x                                                                                                     // Rside 3
    F1y1 = sw ? deg0_3_l  :          deg0_3_l  * (math.abs(val3 * ang) / m)                                   // 180°   // Rside 3 
    F1x2 = E1x2 
    F1y2 = E1y2
    F2x1 = F1x1    
    F2y1 = F1y1
    F2x2 = E2x2    
    F2y2 = E2y2 

    G1x1 = deg0_1_x  
    G1y1 = sw ? deg0_3_l  :          deg0_3_l  * (math.abs(val4 * ang) / m)                                   // 180°   // Lside 4
    G1x2 = sw ? xMid210   : deg0_1_x                                                                                    // Lside 4
    G1y2 = sw ? yMid210   : 0  
    G2x1 = G1x1    
    G2y1 = G1y1
    G2x2 = 
      sw ? math.round(deg210_3_x - (deg210_3_x - deg210_1_x) * (val4 / m))
         : math.round(deg0_1_x   - (deg0_1_x  - deg210_1_x ) * (math.abs(val4) / m))                                    // POINT 4     
    G2y2 = ln4.get_price(G2x2)                                                                                          // POINT 4 

    H1x1 = math.round(
      sw ? math.avg(deg0_1_x, deg240_1_x) 
         : deg0_1_x - ((deg0_1_x - deg240_3_x) * (math.abs(val4 * ang) / m)))                                           // Rside 4 
    H1y1 = l_5.get_price(H1x1)                                                                                          // Rside 4 
    H1x2 = G1x2 
    H1y2 = G1y2
    H2x1 = H1x1    
    H2y1 = H1y1
    H2x2 = G2x2    
    H2y2 = G2y2 

    I1x1 = math.round(
      sw ? math.avg(deg0_1_x, deg240_1_x) 
         : deg0_1_x - ((deg0_1_x - deg240_3_x) * (math.abs(val5 * ang) / m)))                                           // Lside 5 
    I1y1 = l_5.get_price(I1x1)                                                                                          // Lside 5
    I1x2 = sw ? xMid270   : deg0_1_x  
    I1y2 = sw ? yMid270   : 0 
    I2x1 = I1x1    
    I2y1 = I1y1
    I2x2 = 
      sw ? math.round(deg270_3_x - (deg270_3_x - start1) * (val5 / m))
         : math.round(deg0_1_x   - (deg0_1_x   - start1) * (math.abs(val5) / m))                                        // POINT 5 
    I2y2 = ln5.get_price(I2x2)                                                                                          // POINT 5

    J1x1 = math.round(
      sw ? math.avg(deg0_1_x, deg240_1_x) 
         : deg0_1_x - ((deg0_1_x - deg240_3_x) * (math.abs(val5 * ang) / m)))                                           // Rside 5 
    J1y1 = l_6.get_price(J1x1)                                                                                          // Rside 5 
    J1x2 = I1x2                                                                                                         // 0/mid 5 
    J1y2 = I1y2                                                                                                         // 0/mid 5
    J2x1 = J1x1    
    J2y1 = J1y1
    J2x2 = I2x2    
    J2y2 = I2y2 

    K1x1 = math.round(
      sw ? math.avg(deg0_1_x, deg240_1_x) 
         : deg0_1_x - ((deg0_1_x - deg240_3_x) * (math.abs(val6 * ang) / m)))                                           // Lside 6  
    K1y1 = l_6.get_price(K1x1)                                                                                          // Lside 6  
    K1x2 = sw ? xMid330   : deg0_1_x  
    K1y2 = sw ? yMid330   : 0 
    K2x1 = K1x1    
    K2y1 = K1y1
    K2x2 = 
      sw ? math.round(deg210_3_x - (deg210_3_x - deg210_1_x) * (val6 / m))
         : math.round(deg0_1_x   - (deg0_1_x  - deg210_1_x ) * (math.abs(val6) / m))                                    // POINT 6  
    K2y2 = ln6.get_price(K2x2)                                                                                          // POINT 6

    L1x1 = deg0_1_x                                                                                                     // Rside 6
    L1y1 = sw ? deg0_3_h  :           deg0_3_h * (math.abs(val6 * ang) / m)                                             // Rside 6
    L1x2 = K1x2 
    L1y2 = K1y2
    L2x1 = L1x1    
    L2y1 = L1y1
    L2x2 = K2x2    
    L2y2 = K2y2 

    // value labels (points)
    lb1.set_xy(A2x2, A2y2)
    lb2.set_xy(C2x2, C2y2)
    lb3.set_xy(E2x2, E2y2)
    lb4.set_xy(G2x2, G2y2)
    lb5.set_xy(I2x2, I2y2)
    lb6.set_xy(K2x2, K2y2)

    // fills
    lf1.get_line1 ().set_xy1(A1x1, A1y1), lf1.get_line1 ().set_xy2(A1x2, A1y2)
    lf1.get_line2 ().set_xy1(A2x1, A2y1), lf1.get_line2 ().set_xy2(A2x2, A2y2), lf1.set_color (c(val1, 'c'))
    lf2.get_line1 ().set_xy1(B1x1, B1y1), lf2.get_line1 ().set_xy2(B1x2, B1y2)
    lf2.get_line2 ().set_xy1(B2x1 ,B2y1), lf2.get_line2 ().set_xy2(B2x2, B2y2), lf2.set_color (c(val1, 'c'))

    lf3.get_line1 ().set_xy1(C1x1, C1y1), lf3.get_line1 ().set_xy2(C1x2, C1y2)
    lf3.get_line2 ().set_xy1(C2x1, C2y1), lf3.get_line2 ().set_xy2(C2x2, C2y2), lf3.set_color (c(val2, 'c'))
    lf4.get_line1 ().set_xy1(D1x1, D1y1), lf4.get_line1 ().set_xy2(D1x2, D1y2)
    lf4.get_line2 ().set_xy1(D2x1, D2y1), lf4.get_line2 ().set_xy2(D2x2, D2y2), lf4.set_color (c(val2, 'c'))

    lf5.get_line1 ().set_xy1(E1x1, E1y1), lf5.get_line1 ().set_xy2(E1x2, E1y2)
    lf5.get_line2 ().set_xy1(E2x1, E2y1), lf5.get_line2 ().set_xy2(E2x2, E2y2), lf5.set_color (c(val3, 'c'))
    lf6.get_line1 ().set_xy1(F1x1, F1y1), lf6.get_line1 ().set_xy2(F1x2, F1y2)
    lf6.get_line2 ().set_xy1(F2x1, F2y1), lf6.get_line2 ().set_xy2(F2x2, F2y2), lf6.set_color (c(val3, 'c'))

    lf7.get_line1 ().set_xy1(G1x1, G1y1), lf7.get_line1 ().set_xy2(G1x2, G1y2)
    lf7.get_line2 ().set_xy1(G2x1, G2y1), lf7.get_line2 ().set_xy2(G2x2, G2y2), lf7.set_color (c(val4, 'c'))
    lf8.get_line1 ().set_xy1(H1x1, H1y1), lf8.get_line1 ().set_xy2(H1x2, H1y2)
    lf8.get_line2 ().set_xy1(H2x1, H2y1), lf8.get_line2 ().set_xy2(H2x2, H2y2), lf8.set_color (c(val4, 'c'))

    lf9.get_line1 ().set_xy1(I1x1, I1y1), lf9.get_line1 ().set_xy2(I1x2, I1y2)
    lf9.get_line2 ().set_xy1(I2x1, I2y1), lf9.get_line2 ().set_xy2(I2x2, I2y2), lf9.set_color (c(val5, 'c'))
    lf10.get_line1().set_xy1(J1x1, J1y1), lf10.get_line1().set_xy2(J1x2, J1y2)
    lf10.get_line2().set_xy1(J2x1, J2y1), lf10.get_line2().set_xy2(J2x2, J2y2), lf10.set_color(c(val5, 'c'))

    lf11.get_line1().set_xy1(K1x1, K1y1), lf11.get_line1().set_xy2(K1x2, K1y2)
    lf11.get_line2().set_xy1(K2x1, K2y1), lf11.get_line2().set_xy2(K2x2, K2y2), lf11.set_color(c(val6, 'c'))
    lf12.get_line1().set_xy1(L1x1, L1y1), lf12.get_line1().set_xy2(L1x2, L1y2)
    lf12.get_line2().set_xy1(L2x1, L2y1), lf12.get_line2().set_xy2(L2x2, L2y2), lf12.set_color(c(val6, 'c'))

    // units
    pc   = (deg60_1_x - deg0_1_x) / 2
    un2x =  deg60_1_x -       (pc / 2)
    un3x =  deg60_1_x -        pc
    un4x =  deg0_1_x  +       (pc / 2)

    un1.set_xy(deg60_1_x, l_2.get_price(deg60_1_x)), un1.set_text(sw ? str.tostring( m    ) : str.tostring( m    )) 
    un2.set_xy(un2x     , l_2.get_price(un2x     )), un2.set_text(sw ? str.tostring( m / 2) : str.tostring( m/4*3)) 
    un3.set_xy(un3x     , l_2.get_price(un3x     )), un3.set_text(sw ?       '0'            : str.tostring( m / 2))     
    un4.set_xy(un4x     , l_2.get_price(un4x     )), un4.set_text(sw ? str.tostring(-m / 2) : str.tostring( m / 4)) 
    un5.set_xy(deg0_1_x ,                 0       ), un5.set_text(sw ? str.tostring(-m    ) :           '0'       ) 

//-----------------------------------------------------------------------------}
//Table
//-----------------------------------------------------------------------------{
    var tab = table.new(tPos, 4, 7
     , frame_color  = color(na), frame_width=1
     , border_color = color(na), bgcolor = color(na), border_width = 1)
    table.cell(tab, 0, 0, text =   'N°'  , bgcolor = color(na), text_color=cC)
    table.cell(tab, 1, 0, text = 'Prefix', bgcolor = color(na), text_color=cC)
    table.cell(tab, 2, 0, text = 'Ticker', bgcolor = color(na), text_color=cC)
    table.cell(tab, 3, 0, text =   '%'   , bgcolor = color(na), text_color=cC)

    tab(tab, '1', pre1, des1.replace(), naV1, 1)
    tab(tab, '2', pre2, des2.replace(), naV2, 2)
    tab(tab, '3', pre3, des3.replace(), naV3, 3)
    tab(tab, '4', pre4, des4.replace(), naV4, 4)
    tab(tab, '5', pre5, des5.replace(), naV5, 5)
    tab(tab, '6', pre6, des6.replace(), naV6, 6)

//-----------------------------------------------------------------------------}
//Plots
//-----------------------------------------------------------------------------{
plot(hi1, 'Edge'    , color=cP0, display=display.pane)
plot(lo1, 'Edge'    , color=cP0, display=display.pane)
plot(hi1, 'circle 1', color=cP1, display=display.pane, style=plot.style_area)
plot(lo1, 'circle 1', color=cP1, display=display.pane, style=plot.style_area)
plot(hi2, 'circle 2', color=cP2, display=display.pane)
plot(lo2, 'circle 2', color=cP2, display=display.pane)
plot(hi3, 'circle 3', color=cP3, display=display.pane)
plot(lo3, 'circle 3', color=cP3, display=display.pane)
plot(hi4, 'circle 4', color=cP4, display=display.pane)
plot(lo4, 'circle 4', color=cP4, display=display.pane)
//-----------------------------------------------------------------------------}