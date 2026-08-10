using System.Reflection;
using System.Runtime.Loader;

const string defaultLuminaDirectory = @"C:\Users\user\AppData\Roaming\XIVLauncher\addon\Hooks\15.0.3.1";
const string defaultGameDirectory = @"D:\Juegos\ffxiv\SquareEnix\FINAL FANTASY XIV - A Realm Reborn\game\sqpack";
const string defaultAllaganDirectory = @"C:\Users\user\AppData\Roaming\XIVLauncher\installedPlugins\AutoHook\6.0.0.90";

var luminaDirectory = Environment.GetEnvironmentVariable("FFXIV_LUMINA_DIR") ?? defaultLuminaDirectory;
var gameDirectory = Environment.GetEnvironmentVariable("FFXIV_GAME_DIR") ?? defaultGameDirectory;
var allaganDirectory = Environment.GetEnvironmentVariable("FFXIV_ALLAGAN_DIR") ?? defaultAllaganDirectory;
var snapshotOutputPath = ReadCommandLineOption(args, "--snapshot-out");
var luminaAssemblyPath = Path.Combine(luminaDirectory, "Lumina.dll");
var excelAssemblyPath = Path.Combine(luminaDirectory, "Lumina.Excel.dll");

if (!File.Exists(luminaAssemblyPath) || !File.Exists(excelAssemblyPath))
{
    Console.Error.WriteLine($"Lumina assemblies not found in {luminaDirectory}");
    return 2;
}

AssemblyLoadContext.Default.Resolving += (_, assemblyName) =>
{
    foreach (var directory in new[] { luminaDirectory, allaganDirectory })
    {
        var dependencyPath = Path.Combine(directory, $"{assemblyName.Name}.dll");
        if (File.Exists(dependencyPath))
        {
            return AssemblyLoadContext.Default.LoadFromAssemblyPath(dependencyPath);
        }
    }
    return null;
};

var luminaAssembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(luminaAssemblyPath);
var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(excelAssemblyPath);
Type[] types;
var loaderErrors = new List<string>();
try
{
    types = assembly.GetTypes();
}
catch (ReflectionTypeLoadException exception)
{
    types = exception.Types.Where(type => type is not null).Cast<Type>().ToArray();
    loaderErrors.AddRange(
        exception.LoaderExceptions
            .Where(error => error is not null)
            .Select(error => error!.Message)
            .Distinct()
    );
}

var interestingTokens = new[]
{
    "SpecialShop",
    "GCScripShop",
    "GCShop",
    "InclusionShop",
    "CollectablesShop",
    "FccShop",
    "DisposalShop",
    "LotteryExchangeShop",
    "Tomestone",
    "GilShop",
    "ENpcBase",
    "ENpcResident",
};

var interestingTypes = types
    .Where(type => interestingTokens.Any(token => type.FullName?.Contains(token, StringComparison.OrdinalIgnoreCase) == true))
    .Select(type => new
    {
        type.FullName,
        type.IsPublic,
        type.IsValueType,
    })
    .OrderBy(type => type.FullName)
    .ToArray();

var specialShopNestedSchema = types
    .Where(type =>
        type.FullName?.StartsWith("Lumina.Excel.Sheets.SpecialShop+", StringComparison.Ordinal) == true
    )
    .Select(type => new
    {
        type.FullName,
        properties = type
            .GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            .Select(property => new { property.Name, type = FriendlyTypeName(property.PropertyType) })
            .ToArray(),
    })
    .ToArray();

var untypedRowRefType = luminaAssembly.GetType("Lumina.Excel.RowRef");
var untypedRowRefApi = untypedRowRefType is null
    ? null
    : new
    {
        properties = untypedRowRefType
            .GetProperties(BindingFlags.Instance | BindingFlags.Public)
            .Select(property => new { property.Name, type = FriendlyTypeName(property.PropertyType) })
            .ToArray(),
        methods = untypedRowRefType
            .GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly)
            .Select(method => method.ToString())
            .ToArray(),
    };

var gameDataType = luminaAssembly.GetType("Lumina.GameData");
var gameDataApi = gameDataType is null
    ? null
    : new
    {
        constructors = gameDataType
            .GetConstructors()
            .Select(constructor => constructor.ToString())
            .ToArray(),
        methods = gameDataType
            .GetMethods(BindingFlags.Instance | BindingFlags.Public)
            .Where(method => method.Name.Contains("Excel", StringComparison.OrdinalIgnoreCase))
            .Select(method => method.ToString())
            .OrderBy(method => method)
            .ToArray(),
    };

var requestedSheets = new[]
{
    "SpecialShop",
    "GCScripShopItem",
    "GCShop",
    "InclusionShop",
    "CollectablesShop",
    "FccShop",
    "DisposalShop",
    "LotteryExchangeShop",
    "TomestoneConvert",
    "Tomestones",
    "TomestonesItem",
    "GilShop",
    "ENpcBase",
    "ENpcResident",
    "Item",
    "ItemSearchCategory",
    "ItemUICategory",
    "Recipe",
    "CraftType",
    "GatheringItem",
    "FishParameter",
    "SpearfishingItem",
    "Level",
};

var localGameProbe = ProbeLocalGameData(
    gameDirectory,
    luminaAssembly,
    assembly,
    requestedSheets,
    snapshotOutputPath
);
var helperLibraryProbe = ProbeHelperLibrary(allaganDirectory);

var result = new
{
    status = loaderErrors.Count == 0 ? "PASS" : "WARN",
    assembly = new
    {
        path = excelAssemblyPath,
        name = assembly.GetName().Name,
        version = assembly.GetName().Version?.ToString(),
        totalTypesLoaded = types.Length,
    },
    interestingTypes,
    specialShopNestedSchema,
    untypedRowRefApi,
    gameDataApi,
    currencyResolverSelfTest = CurrencyResolver.SelfTest(),
    localGameProbe,
    helperLibraryProbe,
    loaderErrors,
};

Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(
    result,
    new System.Text.Json.JsonSerializerOptions { WriteIndented = true }
));

return loaderErrors.Count == 0 ? 0 : 1;

static object ProbeHelperLibrary(string directory)
{
    var path = Path.Combine(directory, "AllaganLib.GameSheets.dll");
    if (!File.Exists(path))
    {
        return new { status = "SKIPPED", path, error = "Helper library not installed." };
    }

    try
    {
        var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(path);
        Type[] types;
        string[] loaderErrors;
        try
        {
            types = assembly.GetTypes();
            loaderErrors = Array.Empty<string>();
        }
        catch (ReflectionTypeLoadException exception)
        {
            types = exception.Types.Where(type => type is not null).Cast<Type>().ToArray();
            loaderErrors = exception.LoaderExceptions
                .Where(error => error is not null)
                .Select(error => error!.Message)
                .Distinct()
                .ToArray();
        }

        var matches = types
            .Where(type =>
                type.FullName?.Contains("SpecialShop", StringComparison.OrdinalIgnoreCase) == true
                || type.FullName?.Contains("ShopListing", StringComparison.OrdinalIgnoreCase) == true
                || type.FullName?.Contains("Currency", StringComparison.OrdinalIgnoreCase) == true
            )
            .Select(type => new
            {
                type.FullName,
                type.IsPublic,
                constructors = type
                    .GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    .Select(constructor => constructor.ToString())
                    .ToArray(),
                methods = type
                    .GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly)
                    .Select(method => method.ToString())
                    .OrderBy(method => method)
                    .ToArray(),
                properties = type
                    .GetProperties(BindingFlags.Instance | BindingFlags.Public)
                    .Select(property => new { property.Name, type = FriendlyTypeName(property.PropertyType) })
                    .ToArray(),
            })
            .OrderBy(type => type.FullName)
            .ToArray();

        return new
        {
            status = loaderErrors.Length == 0 ? "PASS" : "WARN",
            path,
            totalTypesLoaded = types.Length,
            matches,
            loaderErrors,
        };
    }
    catch (Exception exception)
    {
        return new { status = "FAIL", path, error = UnwrapException(exception).Message };
    }
}

static object ProbeLocalGameData(
    string gameDirectory,
    Assembly luminaAssembly,
    Assembly excelAssembly,
    IReadOnlyList<string> requestedSheets,
    string? snapshotOutputPath
)
{
    if (!Directory.Exists(gameDirectory))
    {
        return new
        {
            status = "SKIPPED",
            gameDirectory,
            error = "Game directory not found.",
            sheets = Array.Empty<object>(),
        };
    }

    var gameDataType = luminaAssembly.GetType("Lumina.GameData")
        ?? throw new InvalidOperationException("Lumina.GameData type was not found.");
    var optionsType = luminaAssembly.GetType("Lumina.LuminaOptions")
        ?? throw new InvalidOperationException("Lumina.LuminaOptions type was not found.");
    var options = Activator.CreateInstance(optionsType)
        ?? throw new InvalidOperationException("Could not construct LuminaOptions.");
    var constructor = gameDataType.GetConstructor(new[] { typeof(string), optionsType })
        ?? throw new InvalidOperationException("Expected GameData constructor was not found.");

    object gameData;
    try
    {
        gameData = constructor.Invoke(new[] { gameDirectory, options });
    }
    catch (TargetInvocationException exception)
    {
        return new
        {
            status = "FAIL",
            gameDirectory,
            error = exception.InnerException?.Message ?? exception.Message,
            sheets = Array.Empty<object>(),
        };
    }

    var getExcelSheet = gameDataType
        .GetMethods(BindingFlags.Instance | BindingFlags.Public)
        .Single(method => method.Name == "GetExcelSheet" && method.IsGenericMethodDefinition);
    var getSubrowExcelSheet = gameDataType
        .GetMethods(BindingFlags.Instance | BindingFlags.Public)
        .Single(method => method.Name == "GetSubrowExcelSheet" && method.IsGenericMethodDefinition);

    var sheetResults = new List<object>();
    foreach (var sheetName in requestedSheets)
    {
        var rowType = excelAssembly.GetType($"Lumina.Excel.Sheets.{sheetName}");
        if (rowType is null)
        {
            sheetResults.Add(new { sheet = sheetName, status = "MISSING_TYPE" });
            continue;
        }

        sheetResults.Add(ProbeSheet(gameData, getExcelSheet, getSubrowExcelSheet, rowType, sheetName));
    }

    var specialShopType = excelAssembly.GetType("Lumina.Excel.Sheets.SpecialShop");
    var itemType = excelAssembly.GetType("Lumina.Excel.Sheets.Item");
    var itemSearchCategoryType = excelAssembly.GetType("Lumina.Excel.Sheets.ItemSearchCategory");
    var itemUiCategoryType = excelAssembly.GetType("Lumina.Excel.Sheets.ItemUICategory");
    var recipeType = excelAssembly.GetType("Lumina.Excel.Sheets.Recipe");
    var craftType = excelAssembly.GetType("Lumina.Excel.Sheets.CraftType");
    var gatheringItemType = excelAssembly.GetType("Lumina.Excel.Sheets.GatheringItem");
    var fishParameterType = excelAssembly.GetType("Lumina.Excel.Sheets.FishParameter");
    var spearfishingItemType = excelAssembly.GetType("Lumina.Excel.Sheets.SpearfishingItem");
    var itemCatalog = itemType is null
        ? null
        : BuildItemCatalog(
            gameData,
            getExcelSheet,
            itemType,
            itemSearchCategoryType,
            itemUiCategoryType,
            recipeType,
            craftType,
            gatheringItemType,
            fishParameterType,
            spearfishingItemType
        );
    var tomestonesItemType = excelAssembly.GetType("Lumina.Excel.Sheets.TomestonesItem");
    var tomestoneCatalog = tomestonesItemType is null
        ? null
        : BuildTomestoneCatalog(gameData, getExcelSheet, tomestonesItemType, itemCatalog);
    var enpcBaseType = excelAssembly.GetType("Lumina.Excel.Sheets.ENpcBase");
    var enpcResidentType = excelAssembly.GetType("Lumina.Excel.Sheets.ENpcResident");
    var levelType = excelAssembly.GetType("Lumina.Excel.Sheets.Level");
    var gameVersion = ReadGameVersion(gameDirectory);
    var normalizedSnapshot = snapshotOutputPath is null
        ? new { status = "SKIPPED", reason = "Pass --snapshot-out <path> to export normalized SpecialShop rows." } as object
        : specialShopType is null || itemCatalog is null
            ? new { status = "MISSING_TYPE", error = "SpecialShop or Item sheet type was not found." } as object
            : ExportSpecialShopSnapshot(
                gameData,
                getExcelSheet,
                specialShopType,
                itemCatalog,
                tomestoneCatalog,
                gameVersion,
                snapshotOutputPath
            );
    var domainAnalysis = new
    {
        specialShop = specialShopType is null
            ? new { status = "MISSING_TYPE" } as object
            : AnalyzeSpecialShop(gameData, getExcelSheet, specialShopType, itemCatalog, tomestoneCatalog),
        items = itemCatalog is null
            ? new { status = "MISSING_TYPE" } as object
            : itemCatalog.Analysis,
        tomestones = tomestoneCatalog is null
            ? new { status = "MISSING_TYPE" } as object
            : tomestoneCatalog.Analysis,
        npcLocations = specialShopType is null || enpcBaseType is null || enpcResidentType is null || levelType is null
            ? new { status = "MISSING_TYPE" } as object
            : AnalyzeNpcLocations(
                gameData,
                getExcelSheet,
                specialShopType,
                enpcBaseType,
                enpcResidentType,
                levelType
            ),
    };

    if (gameData is IDisposable disposable)
    {
        disposable.Dispose();
    }

    var failed = sheetResults.Count(result =>
    {
        var statusProperty = result.GetType().GetProperty("status");
        return statusProperty?.GetValue(result)?.ToString() != "PASS";
    });

    return new
    {
        status = failed == 0 ? "PASS" : "WARN",
        gameDirectory,
        gameVersion = ReadGameVersion(gameDirectory),
        sheetsRequested = requestedSheets.Count,
        sheetsPassed = requestedSheets.Count - failed,
        sheetsFailed = failed,
        sheets = sheetResults,
        normalizedSnapshot,
        domainAnalysis,
    };
}

static object ExportSpecialShopSnapshot(
    object gameData,
    MethodInfo getExcelSheet,
    Type rowType,
    ItemCatalog itemCatalog,
    TomestoneCatalog? tomestoneCatalog,
    string? gameVersion,
    string outputPath
)
{
    try
    {
        var sheet = getExcelSheet.MakeGenericMethod(rowType).Invoke(gameData, new object?[] { null, null });
        if (sheet is not System.Collections.IEnumerable rows)
        {
            return new { status = "FAIL", error = "SpecialShop sheet is not enumerable." };
        }

        var shops = new List<NormalizedShop>();
        var offers = new List<NormalizedOffer>();
        var costs = new List<NormalizedOfferCost>();
        var rewards = new List<NormalizedOfferReward>();
        var requirements = new List<NormalizedRequirement>();
        var assetIds = new HashSet<uint>();
        var sourceRows = 0;
        var rowsIgnored = 0;

        foreach (var row in rows.Cast<object>())
        {
            sourceRows++;
            var shopId = ReadRowId(row) ?? 0;
            if (shopId == 0)
            {
                rowsIgnored++;
                continue;
            }
            var useCurrencyType = Convert.ToByte(ReadProperty(row, "UseCurrencyType") ?? (byte)0);
            shops.Add(new NormalizedShop(
                shopId,
                ReadProperty(row, "Name")?.ToString(),
                useCurrencyType
            ));
            AddRequirement(requirements, shopId, null, "QUEST", ReadRowRefId(ReadProperty(row, "Quest")));
            AddRequirement(
                requirements,
                shopId,
                null,
                "CONTENT_FINDER_CONDITION",
                ReadRowRefId(ReadProperty(row, "RequiredContentFinderCondition"))
            );
            AddRequirement(requirements, shopId, null, "FESTIVAL", ReadRowRefId(ReadProperty(row, "RequiredFestival")));

            var groupIndex = -1;
            var rowOfferCount = 0;
            foreach (var itemGroup in EnumerateProperty(row, "Item"))
            {
                groupIndex++;
                var groupRewards = new List<NormalizedOfferReward>();
                var rewardIndex = 0;
                foreach (var reward in EnumerateProperty(itemGroup, "ReceiveItems"))
                {
                    var itemId = ReadRowRefId(ReadProperty(reward, "Item"));
                    var quantity = ReadUnsigned(ReadProperty(reward, "ReceiveCount"));
                    if (itemId == 0 || quantity == 0)
                    {
                        continue;
                    }
                    var isHq = Convert.ToBoolean(ReadProperty(reward, "ReceiveHq") ?? false);
                    groupRewards.Add(new NormalizedOfferReward(
                        shopId,
                        groupIndex,
                        rewardIndex++,
                        itemId,
                        quantity,
                        isHq
                    ));
                    assetIds.Add(itemId);
                }
                if (groupRewards.Count == 0)
                {
                    continue;
                }

                rowOfferCount++;
                var groupCosts = new List<NormalizedOfferCost>();
                var costIndex = 0;
                var hasNonPositiveCost = false;
                foreach (var cost in EnumerateProperty(itemGroup, "ItemCosts"))
                {
                    var rawItemId = ReadRowRefId(ReadProperty(cost, "ItemCost"));
                    var quantity = ReadUnsigned(ReadProperty(cost, "CurrencyCost"));
                    var costType = Convert.ToByte(ReadProperty(cost, "CostType") ?? (byte)0);
                    if (rawItemId == 0 && quantity == 0)
                    {
                        continue;
                    }
                    if (quantity == 0)
                    {
                        hasNonPositiveCost = true;
                        continue;
                    }
                    var resolvedItemId = CurrencyResolver.Resolve(
                        shopId,
                        rawItemId,
                        useCurrencyType,
                        tomestoneCatalog?.ItemByTomestoneId
                    );
                    groupCosts.Add(new NormalizedOfferCost(
                        shopId,
                        groupIndex,
                        costIndex++,
                        rawItemId,
                        resolvedItemId == 0 ? null : resolvedItemId,
                        quantity,
                        costType
                    ));
                    if (resolvedItemId > 0)
                    {
                        assetIds.Add(resolvedItemId);
                    }
                }

                var parseStatus = !hasNonPositiveCost
                    && groupCosts.Count > 0
                    && groupCosts.All(cost => cost.ItemId is not null)
                    ? "PARSED"
                    : "INCOMPLETE_COST";
                offers.Add(new NormalizedOffer(shopId, groupIndex, $"{shopId}:{groupIndex}", parseStatus));
                costs.AddRange(groupCosts);
                rewards.AddRange(groupRewards);
                AddRequirement(
                    requirements,
                    shopId,
                    groupIndex,
                    "QUEST",
                    ReadRowRefId(ReadProperty(itemGroup, "Quest"))
                );
                AddRequirement(
                    requirements,
                    shopId,
                    groupIndex,
                    "ACHIEVEMENT",
                    ReadRowRefId(ReadProperty(itemGroup, "AchievementUnlock"))
                );
            }
            if (rowOfferCount == 0)
            {
                rowsIgnored++;
            }
        }

        // Keep the complete Item catalog. SpecialShop only references a subset, but
        // market/expansion analysis needs categories for every tradeable item.
        var assets = itemCatalog.Names.Keys
            .OrderBy(itemId => itemId)
            .Select(itemId => new NormalizedAsset(
                itemId,
                itemCatalog.Names.GetValueOrDefault(itemId),
                itemCatalog.MarketableCandidates.Contains(itemId),
                itemCatalog.SearchCategoryByItem.GetValueOrDefault(itemId) is var searchCategoryId && searchCategoryId > 0
                    ? searchCategoryId
                    : null,
                itemCatalog.SearchCategoryNames.GetValueOrDefault(
                    itemCatalog.SearchCategoryByItem.GetValueOrDefault(itemId)
                ),
                itemCatalog.UiCategoryByItem.GetValueOrDefault(itemId) is var uiCategoryId && uiCategoryId > 0
                    ? uiCategoryId
                    : null,
                itemCatalog.UiCategoryNames.GetValueOrDefault(
                    itemCatalog.UiCategoryByItem.GetValueOrDefault(itemId)
                ),
                itemCatalog.CraftTypesByItem.ContainsKey(itemId),
                itemCatalog.CraftTypesByItem.GetValueOrDefault(itemId),
                itemCatalog.GatherableItems.Contains(itemId),
                itemCatalog.FishingItems.Contains(itemId)
                    ? "FISHING"
                    : itemCatalog.GatherableItems.Contains(itemId)
                        ? "MINER_BOTANIST"
                        : null
            ))
            .ToArray();
        var envelope = new NormalizedSnapshot(
            3,
            "sqpack",
            gameVersion ?? "unknown",
            DateTimeOffset.UtcNow.ToString("O"),
            assets,
            shops,
            offers,
            costs,
            rewards,
            requirements,
            new CoverageAudit(sourceRows, offers.Count, rowsIgnored, 0)
        );

        var absolutePath = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(absolutePath)!);
        File.WriteAllText(
            absolutePath,
            System.Text.Json.JsonSerializer.Serialize(
                envelope,
                new System.Text.Json.JsonSerializerOptions
                {
                    WriteIndented = false,
                    PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase,
                }
            )
        );
        return new
        {
            status = "PASS",
            path = absolutePath,
            schemaVersion = envelope.SchemaVersion,
            gameVersion = envelope.GameVersion,
            assets = assets.Length,
            shops = shops.Count,
            offers = offers.Count,
            costs = costs.Count,
            rewards = rewards.Count,
            requirements = requirements.Count,
        };
    }
    catch (Exception exception)
    {
        return new { status = "FAIL", error = UnwrapException(exception).Message };
    }
}

static void AddRequirement(
    ICollection<NormalizedRequirement> requirements,
    uint shopId,
    int? offerIndex,
    string requirementType,
    uint value
)
{
    if (value > 0)
    {
        requirements.Add(new NormalizedRequirement(shopId, offerIndex, requirementType, value));
    }
}

static object AnalyzeNpcLocations(
    object gameData,
    MethodInfo getExcelSheet,
    Type specialShopType,
    Type enpcBaseType,
    Type enpcResidentType,
    Type levelType
)
{
    try
    {
        var shopRows = getExcelSheet.MakeGenericMethod(specialShopType).Invoke(gameData, new object?[] { null, null });
        var npcRows = getExcelSheet.MakeGenericMethod(enpcBaseType).Invoke(gameData, new object?[] { null, null });
        var residentRows = getExcelSheet.MakeGenericMethod(enpcResidentType).Invoke(gameData, new object?[] { null, null });
        var levelRows = getExcelSheet.MakeGenericMethod(levelType).Invoke(gameData, new object?[] { null, null });
        if (
            shopRows is not System.Collections.IEnumerable shops
            || npcRows is not System.Collections.IEnumerable npcs
            || residentRows is not System.Collections.IEnumerable residents
            || levelRows is not System.Collections.IEnumerable levels
        )
        {
            return new { status = "FAIL", error = "One or more NPC/location sheets are not enumerable." };
        }

        var shopIds = new HashSet<uint>();
        var activeShopIds = new HashSet<uint>();
        foreach (var shop in shops.Cast<object>())
        {
            var shopId = ReadRowId(shop) ?? 0;
            if (shopId == 0)
            {
                continue;
            }
            shopIds.Add(shopId);
            var hasReward = EnumerateProperty(shop, "Item").Any(itemGroup =>
                EnumerateProperty(itemGroup, "ReceiveItems").Any(reward =>
                    ReadRowRefId(ReadProperty(reward, "Item")) > 0
                    && ReadUnsigned(ReadProperty(reward, "ReceiveCount")) > 0
                )
            );
            if (hasReward)
            {
                activeShopIds.Add(shopId);
            }
        }
        var shopToNpcs = new Dictionary<uint, HashSet<uint>>();
        var npcIds = new HashSet<uint>();
        foreach (var npc in npcs.Cast<object>())
        {
            var npcId = ReadRowId(npc) ?? 0;
            foreach (var shopRef in EnumerateProperty(npc, "ENpcData"))
            {
                var rowType = ReadProperty(shopRef, "RowType") as Type;
                var shopId = ReadRowRefId(shopRef);
                if (rowType != specialShopType || !shopIds.Contains(shopId))
                {
                    continue;
                }
                if (!shopToNpcs.TryGetValue(shopId, out var linkedNpcs))
                {
                    linkedNpcs = new HashSet<uint>();
                    shopToNpcs[shopId] = linkedNpcs;
                }
                linkedNpcs.Add(npcId);
                npcIds.Add(npcId);
            }
        }

        var npcNames = residents
            .Cast<object>()
            .Where(row => npcIds.Contains(ReadRowId(row) ?? 0))
            .ToDictionary(
                row => ReadRowId(row) ?? 0,
                row => ReadProperty(row, "Singular")?.ToString() ?? string.Empty
            );
        var npcToShops = shopToNpcs
            .SelectMany(pair => pair.Value.Select(npcId => new { shopId = pair.Key, npcId }))
            .GroupBy(link => link.npcId)
            .ToDictionary(group => group.Key, group => group.Select(link => link.shopId).ToHashSet());
        var locatedNpcs = new HashSet<uint>();
        var locatedShops = new HashSet<uint>();
        var locationMatches = 0;
        var samples = new List<object>();
        foreach (var level in levels.Cast<object>())
        {
            var objectRef = ReadProperty(level, "Object");
            var rowType = objectRef is null ? null : ReadProperty(objectRef, "RowType") as Type;
            var npcId = ReadRowRefId(objectRef);
            if (rowType != enpcBaseType || !npcToShops.TryGetValue(npcId, out var linkedShops))
            {
                continue;
            }
            locationMatches++;
            locatedNpcs.Add(npcId);
            foreach (var shopId in linkedShops)
            {
                locatedShops.Add(shopId);
                if (samples.Count < 10)
                {
                    samples.Add(new
                    {
                        shopId,
                        npcId,
                        npcName = npcNames.GetValueOrDefault(npcId),
                        levelRowId = ReadRowId(level),
                        mapId = ReadRowRefId(ReadProperty(level, "Map")),
                        territoryId = ReadRowRefId(ReadProperty(level, "Territory")),
                        x = Convert.ToSingle(ReadProperty(level, "X") ?? 0f),
                        y = Convert.ToSingle(ReadProperty(level, "Y") ?? 0f),
                        z = Convert.ToSingle(ReadProperty(level, "Z") ?? 0f),
                    });
                }
            }
        }

        return new
        {
            status = "PASS",
            specialShopRows = shopIds.Count,
            shopsWithOffers = activeShopIds.Count,
            shopsLinkedToNpc = shopToNpcs.Count,
            shopsWithoutNpc = shopIds.Count - shopToNpcs.Count,
            activeShopsLinkedToNpc = activeShopIds.Count(shopToNpcs.ContainsKey),
            activeShopsWithoutNpc = activeShopIds.Count(shopId => !shopToNpcs.ContainsKey(shopId)),
            distinctShopNpcs = npcIds.Count,
            shopNpcLinks = shopToNpcs.Sum(pair => pair.Value.Count),
            npcsWithLevelLocation = locatedNpcs.Count,
            shopsWithLevelLocation = locatedShops.Count,
            shopsWithoutLevelLocation = shopIds.Count - locatedShops.Count,
            activeShopsWithLevelLocation = activeShopIds.Count(locatedShops.Contains),
            activeShopsWithoutLevelLocation = activeShopIds.Count(shopId => !locatedShops.Contains(shopId)),
            locationMatches,
            samples,
            note = "Counts include obsolete/internal SpecialShop rows; production coverage is measured again over active offers only.",
        };
    }
    catch (Exception exception)
    {
        return new { status = "FAIL", error = UnwrapException(exception).Message };
    }
}

static object AnalyzeSpecialShop(
    object gameData,
    MethodInfo getExcelSheet,
    Type rowType,
    ItemCatalog? itemCatalog,
    TomestoneCatalog? tomestoneCatalog
)
{
    try
    {
        var sheet = getExcelSheet.MakeGenericMethod(rowType).Invoke(gameData, new object?[] { null, null });
        if (sheet is not System.Collections.IEnumerable rows)
        {
            return new { status = "FAIL", error = "SpecialShop sheet is not enumerable." };
        }

        var shopRows = 0;
        var shopsWithOffers = 0;
        var offerGroups = 0;
        var rewardComponents = 0;
        var costComponents = 0;
        var offersWithMultipleCosts = 0;
        var offersWithoutResolvedCost = 0;
        var topLevelRequirements = 0;
        var offerRequirements = 0;
        var costTypes = new HashSet<byte>();
        var costTypeFrequency = new Dictionary<byte, int>();
        var useCurrencyTypeFrequency = new Dictionary<byte, int>();
        var rewardItemIds = new HashSet<uint>();
        var costItemIds = new HashSet<uint>();
        var costItemFrequency = new Dictionary<uint, int>();
        var resolvedCostItemFrequency = new Dictionary<uint, int>();
        var convertedCurrencyComponents = 0;
        var poeticsCostComponents = 0;
        var samples = new List<object>();

        foreach (var row in rows)
        {
            if (row is null)
            {
                continue;
            }
            shopRows++;
            var shopRowId = ReadRowId(row) ?? 0;
            var useCurrencyType = Convert.ToByte(ReadProperty(row, "UseCurrencyType") ?? (byte)0);
            useCurrencyTypeFrequency[useCurrencyType] = useCurrencyTypeFrequency.GetValueOrDefault(useCurrencyType) + 1;
            if (
                ReadRowRefId(ReadProperty(row, "Quest")) > 0
                || ReadRowRefId(ReadProperty(row, "RequiredContentFinderCondition")) > 0
                || ReadRowRefId(ReadProperty(row, "RequiredFestival")) > 0
            )
            {
                topLevelRequirements++;
            }

            var rowHasOffer = false;
            foreach (var itemGroup in EnumerateProperty(row, "Item"))
            {
                var rewards = new List<object>();
                foreach (var reward in EnumerateProperty(itemGroup, "ReceiveItems"))
                {
                    var itemId = ReadRowRefId(ReadProperty(reward, "Item"));
                    var quantity = ReadUnsigned(ReadProperty(reward, "ReceiveCount"));
                    if (itemId == 0 || quantity == 0)
                    {
                        continue;
                    }
                    rewardComponents++;
                    rewardItemIds.Add(itemId);
                    rewards.Add(new { itemId, quantity });
                }
                if (rewards.Count == 0)
                {
                    continue;
                }

                rowHasOffer = true;
                offerGroups++;
                if (
                    ReadRowRefId(ReadProperty(itemGroup, "Quest")) > 0
                    || ReadRowRefId(ReadProperty(itemGroup, "AchievementUnlock")) > 0
                )
                {
                    offerRequirements++;
                }

                var costs = new List<object>();
                foreach (var cost in EnumerateProperty(itemGroup, "ItemCosts"))
                {
                    var itemId = ReadRowRefId(ReadProperty(cost, "ItemCost"));
                    var quantity = ReadUnsigned(ReadProperty(cost, "CurrencyCost"));
                    var costType = Convert.ToByte(ReadProperty(cost, "CostType") ?? (byte)0);
                    if (itemId == 0 && quantity == 0)
                    {
                        continue;
                    }
                    costComponents++;
                    costTypes.Add(costType);
                    costTypeFrequency[costType] = costTypeFrequency.GetValueOrDefault(costType) + 1;
                    if (itemId > 0)
                    {
                        costItemIds.Add(itemId);
                        costItemFrequency[itemId] = costItemFrequency.GetValueOrDefault(itemId) + 1;
                    }
                    var resolvedCurrencyItemId = CurrencyResolver.Resolve(
                        shopRowId,
                        itemId,
                        useCurrencyType,
                        tomestoneCatalog?.ItemByTomestoneId
                    );
                    if (resolvedCurrencyItemId != itemId)
                    {
                        convertedCurrencyComponents++;
                    }
                    if (resolvedCurrencyItemId > 0)
                    {
                        resolvedCostItemFrequency[resolvedCurrencyItemId] =
                            resolvedCostItemFrequency.GetValueOrDefault(resolvedCurrencyItemId) + 1;
                    }
                    if (
                        itemCatalog?.Names.GetValueOrDefault(resolvedCurrencyItemId)?.Contains(
                            "Poetics",
                            StringComparison.OrdinalIgnoreCase
                        ) == true
                    )
                    {
                        poeticsCostComponents++;
                    }
                    costs.Add(new
                    {
                        rawItemId = itemId,
                        resolvedCurrencyItemId,
                        currencyName = itemCatalog?.Names.GetValueOrDefault(resolvedCurrencyItemId),
                        quantity,
                        costType,
                    });
                }

                if (costs.Count > 1)
                {
                    offersWithMultipleCosts++;
                }
                if (costs.Count == 0 || costs.Any(cost => ReadAnonymousUInt(cost, "resolvedCurrencyItemId") == 0))
                {
                    offersWithoutResolvedCost++;
                }
                if (samples.Count < 5)
                {
                    samples.Add(new
                    {
                        shopRowId,
                        useCurrencyType,
                        rewards,
                        costs,
                    });
                }
            }

            if (rowHasOffer)
            {
                shopsWithOffers++;
            }
        }

        return new
        {
            status = "PASS",
            shopRows,
            shopsWithOffers,
            offerGroups,
            rewardComponents,
            distinctRewardItems = rewardItemIds.Count,
            costComponents,
            distinctCostItems = costItemIds.Count,
            costTypes = costTypes.OrderBy(value => value).Select(value => (int)value).ToArray(),
            costTypeFrequency = costTypeFrequency
                .OrderBy(pair => pair.Key)
                .Select(pair => new { costType = (int)pair.Key, costComponents = pair.Value })
                .ToArray(),
            useCurrencyTypeFrequency = useCurrencyTypeFrequency
                .OrderByDescending(pair => pair.Value)
                .ThenBy(pair => pair.Key)
                .Select(pair => new { useCurrencyType = (int)pair.Key, shopRows = pair.Value })
                .ToArray(),
            convertedCurrencyComponents,
            offersWithMultipleCosts,
            offersWithoutResolvedCost,
            topLevelRequirements,
            offerRequirements,
            poeticsCostComponents,
            resolvedPoeticsCurrencies = resolvedCostItemFrequency
                .Where(pair =>
                    itemCatalog?.Names.GetValueOrDefault(pair.Key)?.Contains("Poetics", StringComparison.OrdinalIgnoreCase)
                    == true
                )
                .Select(pair => new
                {
                    itemId = pair.Key,
                    name = itemCatalog?.Names.GetValueOrDefault(pair.Key),
                    costComponents = pair.Value,
                })
                .ToArray(),
            topRawCostIds = costItemFrequency
                .OrderByDescending(pair => pair.Value)
                .ThenBy(pair => pair.Key)
                .Take(20)
                .Select(pair => new
                {
                    itemId = pair.Key,
                    name = itemCatalog?.Names.GetValueOrDefault(pair.Key),
                    costComponents = pair.Value,
                    marketableCandidate = itemCatalog?.MarketableCandidates.Contains(pair.Key),
                })
                .ToArray(),
            topResolvedCurrencies = resolvedCostItemFrequency
                .OrderByDescending(pair => pair.Value)
                .ThenBy(pair => pair.Key)
                .Take(20)
                .Select(pair => new
                {
                    itemId = pair.Key,
                    name = itemCatalog?.Names.GetValueOrDefault(pair.Key),
                    costComponents = pair.Value,
                    marketableCandidate = itemCatalog?.MarketableCandidates.Contains(pair.Key),
                })
                .ToArray(),
            poeticsCostItems = costItemFrequency
                .Where(pair =>
                    itemCatalog?.Names.GetValueOrDefault(pair.Key)?.Contains("Poetics", StringComparison.OrdinalIgnoreCase)
                    == true
                )
                .Select(pair => new
                {
                    itemId = pair.Key,
                    name = itemCatalog?.Names.GetValueOrDefault(pair.Key),
                    costComponents = pair.Value,
                })
                .ToArray(),
            samples,
        };
    }
    catch (Exception exception)
    {
        return new { status = "FAIL", error = UnwrapException(exception).Message };
    }
}

static TomestoneCatalog BuildTomestoneCatalog(
    object gameData,
    MethodInfo getExcelSheet,
    Type rowType,
    ItemCatalog? itemCatalog
)
{
    try
    {
        var sheet = getExcelSheet.MakeGenericMethod(rowType).Invoke(gameData, new object?[] { null, null });
        if (sheet is not System.Collections.IEnumerable rows)
        {
            return new TomestoneCatalog(
                new Dictionary<uint, uint>(),
                new { status = "FAIL", error = "TomestonesItem sheet is not enumerable." }
            );
        }

        var mappings = new List<object>();
        var itemByTomestoneId = new Dictionary<uint, uint>();
        foreach (var row in rows)
        {
            if (row is null)
            {
                continue;
            }
            var itemId = ReadRowRefId(ReadProperty(row, "Item"));
            var tomestoneId = ReadRowRefId(ReadProperty(row, "Tomestones"));
            var currencyInventorySlot = Convert.ToInt32(ReadProperty(row, "CurrencyInventorySlot") ?? -1);
            if (itemId == 0 || tomestoneId == 0 || currencyInventorySlot <= 0)
            {
                continue;
            }
            itemByTomestoneId[tomestoneId] = itemId;
            mappings.Add(new
            {
                rowId = ReadRowId(row),
                tomestoneId,
                itemId,
                name = itemCatalog?.Names.GetValueOrDefault(itemId),
                currencyInventorySlot,
            });
        }

        var analysis = new
        {
            status = "PASS",
            mappingCount = mappings.Count,
            mappings,
            poetics = mappings.Where(mapping =>
            {
                var name = mapping.GetType().GetProperty("name")?.GetValue(mapping)?.ToString();
                return name?.Contains("Poetics", StringComparison.OrdinalIgnoreCase) == true;
            }).ToArray(),
        };
        return new TomestoneCatalog(itemByTomestoneId, analysis);
    }
    catch (Exception exception)
    {
        return new TomestoneCatalog(
            new Dictionary<uint, uint>(),
            new { status = "FAIL", error = UnwrapException(exception).Message }
        );
    }
}

static ItemCatalog BuildItemCatalog(
    object gameData,
    MethodInfo getExcelSheet,
    Type rowType,
    Type? searchCategoryType,
    Type? uiCategoryType,
    Type? recipeType,
    Type? craftType,
    Type? gatheringItemType,
    Type? fishParameterType,
    Type? spearfishingItemType
)
{
    try
    {
        var sheet = getExcelSheet.MakeGenericMethod(rowType).Invoke(gameData, new object?[] { null, null });
        if (sheet is not System.Collections.IEnumerable rows)
        {
            return new ItemCatalog(
                new Dictionary<uint, string>(),
                new HashSet<uint>(),
                new Dictionary<uint, uint>(),
                new Dictionary<uint, string>(),
                new Dictionary<uint, uint>(),
                new Dictionary<uint, string>(),
                new Dictionary<uint, string>(),
                new HashSet<uint>(),
                new HashSet<uint>(),
                new { status = "FAIL", error = "Item sheet is not enumerable." }
            );
        }

        var itemRows = 0;
        var nonZeroItems = 0;
        var tradableFlagItems = 0;
        var searchableItems = 0;
        var marketableCandidates = 0;
        var names = new Dictionary<uint, string>();
        var marketableIds = new HashSet<uint>();
        var searchCategoryByItem = new Dictionary<uint, uint>();
        var uiCategoryByItem = new Dictionary<uint, uint>();
        var searchCategoryNames = BuildCategoryNames(gameData, getExcelSheet, searchCategoryType);
        var uiCategoryNames = BuildCategoryNames(gameData, getExcelSheet, uiCategoryType);
        var craftTypesByItem = BuildCraftTypesByItem(
            gameData,
            getExcelSheet,
            recipeType,
            craftType
        );
        var standardGatheringItems = BuildReferencedItemIds(
            gameData,
            getExcelSheet,
            gatheringItemType,
            "Item"
        );
        var fishingItems = BuildReferencedItemIds(
            gameData,
            getExcelSheet,
            fishParameterType,
            "Item"
        );
        fishingItems.UnionWith(BuildReferencedItemIds(
            gameData,
            getExcelSheet,
            spearfishingItemType,
            "Item"
        ));
        var gatherableItems = new HashSet<uint>(standardGatheringItems);
        gatherableItems.UnionWith(fishingItems);
        foreach (var row in rows)
        {
            if (row is null)
            {
                continue;
            }
            itemRows++;
            var rowId = ReadRowId(row) ?? 0;
            if (rowId == 0)
            {
                continue;
            }
            nonZeroItems++;
            var name = ReadProperty(row, "Name")?.ToString() ?? string.Empty;
            names[rowId] = name;
            var isUntradable = Convert.ToBoolean(ReadProperty(row, "IsUntradable") ?? true);
            var searchCategory = ReadRowRefId(ReadProperty(row, "ItemSearchCategory"));
            var uiCategory = ReadRowRefId(ReadProperty(row, "ItemUICategory"));
            if (searchCategory > 0)
            {
                searchCategoryByItem[rowId] = searchCategory;
            }
            if (uiCategory > 0)
            {
                uiCategoryByItem[rowId] = uiCategory;
            }
            if (!isUntradable)
            {
                tradableFlagItems++;
            }
            if (searchCategory > 0)
            {
                searchableItems++;
            }
            if (!isUntradable && searchCategory > 0)
            {
                marketableCandidates++;
                marketableIds.Add(rowId);
            }
        }

        var analysis = new
        {
            status = "PASS",
            itemRows,
            nonZeroItems,
            tradableFlagItems,
            searchableItems,
            marketableCandidates,
            craftableItems = craftTypesByItem.Count,
            gatherableItems = gatherableItems.Count,
            fishingItems = fishingItems.Count,
            poeticsMatches = names
                .Where(pair => pair.Value.Contains("Poetics", StringComparison.OrdinalIgnoreCase))
                .Select(pair => new { itemId = pair.Key, name = pair.Value })
                .ToArray(),
            note = "Marketable candidates are local static flags, not a replacement for Universalis' canonical marketable list.",
        };
        return new ItemCatalog(
            names,
            marketableIds,
            searchCategoryByItem,
            searchCategoryNames,
            uiCategoryByItem,
            uiCategoryNames,
            craftTypesByItem,
            gatherableItems,
            fishingItems,
            analysis
        );
    }
    catch (Exception exception)
    {
        return new ItemCatalog(
            new Dictionary<uint, string>(),
            new HashSet<uint>(),
            new Dictionary<uint, uint>(),
            new Dictionary<uint, string>(),
            new Dictionary<uint, uint>(),
            new Dictionary<uint, string>(),
            new Dictionary<uint, string>(),
            new HashSet<uint>(),
            new HashSet<uint>(),
            new { status = "FAIL", error = UnwrapException(exception).Message }
        );
    }
}

static Dictionary<uint, string> BuildCraftTypesByItem(
    object gameData,
    MethodInfo getExcelSheet,
    Type? recipeType,
    Type? craftType
)
{
    var result = new Dictionary<uint, HashSet<string>>();
    if (recipeType is null)
    {
        return new Dictionary<uint, string>();
    }
    var craftTypeNames = BuildCategoryNames(gameData, getExcelSheet, craftType);
    var sheet = getExcelSheet.MakeGenericMethod(recipeType).Invoke(gameData, new object?[] { null, null });
    if (sheet is not System.Collections.IEnumerable rows)
    {
        return new Dictionary<uint, string>();
    }
    foreach (var row in rows)
    {
        if (row is null)
        {
            continue;
        }
        var itemId = ReadRowRefId(ReadProperty(row, "ItemResult"));
        if (itemId == 0)
        {
            continue;
        }
        var craftTypeId = ReadRowRefId(ReadProperty(row, "CraftType"));
        var craftName = craftTypeNames.GetValueOrDefault(craftTypeId);
        if (string.IsNullOrWhiteSpace(craftName))
        {
            craftName = craftTypeId > 0 ? $"Craft {craftTypeId}" : "Crafting";
        }
        craftName = craftName switch
        {
            "Crafting" => "Carpenter",
            "Smithing" => "Blacksmith",
            "Armorcraft" => "Armorer",
            "Goldsmithing" => "Goldsmith",
            "Leatherworking" => "Leatherworker",
            "Clothcraft" => "Weaver",
            "Alchemy" => "Alchemist",
            "Cooking" => "Culinarian",
            _ => craftName,
        };
        if (!result.TryGetValue(itemId, out var names))
        {
            names = new HashSet<string>(StringComparer.Ordinal);
            result[itemId] = names;
        }
        names.Add(craftName);
    }
    return result.ToDictionary(
        pair => pair.Key,
        pair => string.Join(" / ", pair.Value.OrderBy(name => name, StringComparer.Ordinal))
    );
}

static HashSet<uint> BuildReferencedItemIds(
    object gameData,
    MethodInfo getExcelSheet,
    Type? rowType,
    string propertyName
)
{
    var result = new HashSet<uint>();
    if (rowType is null)
    {
        return result;
    }
    var sheet = getExcelSheet.MakeGenericMethod(rowType).Invoke(gameData, new object?[] { null, null });
    if (sheet is not System.Collections.IEnumerable rows)
    {
        return result;
    }
    foreach (var row in rows)
    {
        if (row is null)
        {
            continue;
        }
        var itemId = ReadRowRefId(ReadProperty(row, propertyName));
        if (itemId > 0)
        {
            result.Add(itemId);
        }
    }
    return result;
}

static Dictionary<uint, string> BuildCategoryNames(
    object gameData,
    MethodInfo getExcelSheet,
    Type? rowType
)
{
    var names = new Dictionary<uint, string>();
    if (rowType is null)
    {
        return names;
    }
    var sheet = getExcelSheet.MakeGenericMethod(rowType).Invoke(gameData, new object?[] { null, null });
    if (sheet is not System.Collections.IEnumerable rows)
    {
        return names;
    }
    foreach (var row in rows)
    {
        if (row is null)
        {
            continue;
        }
        var rowId = ReadRowId(row) ?? 0;
        var name = ReadProperty(row, "Name")?.ToString();
        if (rowId > 0 && !string.IsNullOrWhiteSpace(name))
        {
            names[rowId] = name;
        }
    }
    return names;
}

static object ProbeSheet(
    object gameData,
    MethodInfo getExcelSheet,
    MethodInfo getSubrowExcelSheet,
    Type rowType,
    string sheetName
)
{
    object? sheet = null;
    var sheetKind = "row";
    string? firstError = null;

    try
    {
        sheet = getExcelSheet.MakeGenericMethod(rowType).Invoke(gameData, new object?[] { null, null });
    }
    catch (Exception exception)
    {
        firstError = UnwrapException(exception).Message;
    }

    if (sheet is null)
    {
        sheetKind = "subrow";
        try
        {
            sheet = getSubrowExcelSheet.MakeGenericMethod(rowType).Invoke(gameData, new object?[] { null, null });
        }
        catch (Exception exception)
        {
            return new
            {
                sheet = sheetName,
                status = "FAIL",
                rowType = rowType.FullName,
                rowError = firstError,
                subrowError = UnwrapException(exception).Message,
            };
        }
    }

    if (sheet is not System.Collections.IEnumerable rows)
    {
        return new
        {
            sheet = sheetName,
            status = "FAIL",
            rowType = rowType.FullName,
            error = "Returned sheet is not enumerable.",
        };
    }

    var declaredRowCount = ReadNumericProperty(sheet, "Count");
    var sampleRowsRead = 0;
    object? firstRow = null;
    try
    {
        foreach (var row in rows)
        {
            firstRow ??= row;
            sampleRowsRead++;
            if (sampleRowsRead >= 3)
            {
                break;
            }
        }
    }
    catch (Exception exception)
    {
        return new
        {
            sheet = sheetName,
            status = "FAIL",
            rowType = rowType.FullName,
            sheetKind,
            rowsReadBeforeFailure = sampleRowsRead,
            error = exception.Message,
        };
    }

    var properties = rowType
        .GetProperties(BindingFlags.Instance | BindingFlags.Public)
        .Select(property => new { property.Name, type = FriendlyTypeName(property.PropertyType) })
        .ToArray();
    var rowId = firstRow is null ? null : ReadRowId(firstRow);

    return new
    {
        sheet = sheetName,
        status = "PASS",
        rowType = rowType.FullName,
        sheetKind,
        declaredRowCount,
        sampleRowsRead,
        firstRowId = rowId,
        properties,
    };
}

static string? ReadGameVersion(string gameDirectory)
{
    var versionPath = Path.Combine(Directory.GetParent(gameDirectory)?.FullName ?? gameDirectory, "ffxivgame.ver");
    return File.Exists(versionPath) ? File.ReadAllText(versionPath).Trim() : null;
}

static string? ReadCommandLineOption(IReadOnlyList<string> arguments, string option)
{
    for (var index = 0; index < arguments.Count; index++)
    {
        if (!string.Equals(arguments[index], option, StringComparison.Ordinal))
        {
            continue;
        }
        if (index + 1 >= arguments.Count || arguments[index + 1].StartsWith("--", StringComparison.Ordinal))
        {
            throw new ArgumentException($"{option} requires a path.");
        }
        return arguments[index + 1];
    }
    return null;
}

static uint? ReadRowId(object row)
{
    var property = row.GetType().GetProperty("RowId");
    var value = property?.GetValue(row);
    return value switch
    {
        uint uintValue => uintValue,
        int intValue when intValue >= 0 => (uint)intValue,
        _ => null,
    };
}

static long? ReadNumericProperty(object instance, string propertyName)
{
    var value = instance.GetType().GetProperty(propertyName)?.GetValue(instance);
    return value is null ? null : Convert.ToInt64(value);
}

static object? ReadProperty(object instance, string propertyName)
{
    return instance.GetType().GetProperty(propertyName)?.GetValue(instance);
}

static IEnumerable<object> EnumerateProperty(object instance, string propertyName)
{
    if (ReadProperty(instance, propertyName) is not System.Collections.IEnumerable values)
    {
        yield break;
    }
    foreach (var value in values)
    {
        if (value is not null)
        {
            yield return value;
        }
    }
}

static uint ReadRowRefId(object? rowReference)
{
    if (rowReference is null)
    {
        return 0;
    }
    var value = rowReference.GetType().GetProperty("RowId")?.GetValue(rowReference);
    return value is null ? 0 : Convert.ToUInt32(value);
}

static uint ReadUnsigned(object? value)
{
    return value is null ? 0 : Convert.ToUInt32(value);
}

static uint ReadAnonymousUInt(object instance, string propertyName)
{
    return ReadUnsigned(instance.GetType().GetProperty(propertyName)?.GetValue(instance));
}

static Exception UnwrapException(Exception exception)
{
    return exception is TargetInvocationException { InnerException: not null } target
        ? target.InnerException!
        : exception;
}

static string FriendlyTypeName(Type type)
{
    if (!type.IsGenericType)
    {
        return type.FullName ?? type.Name;
    }

    var genericName = type.GetGenericTypeDefinition().FullName?.Split('`')[0] ?? type.Name;
    return $"{genericName}<{string.Join(",", type.GetGenericArguments().Select(FriendlyTypeName))}>";
}

sealed record ItemCatalog(
    Dictionary<uint, string> Names,
    HashSet<uint> MarketableCandidates,
    Dictionary<uint, uint> SearchCategoryByItem,
    Dictionary<uint, string> SearchCategoryNames,
    Dictionary<uint, uint> UiCategoryByItem,
    Dictionary<uint, string> UiCategoryNames,
    Dictionary<uint, string> CraftTypesByItem,
    HashSet<uint> GatherableItems,
    HashSet<uint> FishingItems,
    object Analysis
);

sealed record TomestoneCatalog(
    Dictionary<uint, uint> ItemByTomestoneId,
    object Analysis
);

sealed record NormalizedAsset(
    uint ItemId,
    string? Name,
    bool MarketableCandidate,
    uint? SearchCategoryId,
    string? SearchCategoryName,
    uint? UiCategoryId,
    string? UiCategoryName,
    bool Craftable,
    string? CraftTypeName,
    bool Gatherable,
    string? GatheringType
);
sealed record NormalizedShop(uint ShopId, string? Name, byte UseCurrencyType);
sealed record NormalizedOffer(uint ShopId, int OfferIndex, string SourceSubrowKey, string ParseStatus);
sealed record NormalizedOfferCost(
    uint ShopId,
    int OfferIndex,
    int CostIndex,
    uint RawItemId,
    uint? ItemId,
    uint Quantity,
    byte CostType
);
sealed record NormalizedOfferReward(
    uint ShopId,
    int OfferIndex,
    int RewardIndex,
    uint ItemId,
    uint Quantity,
    bool IsHq
);
sealed record NormalizedRequirement(
    uint ShopId,
    int? OfferIndex,
    string RequirementType,
    uint RequirementValue
);
sealed record CoverageAudit(int SourceRows, int OffersEmitted, int RowsIgnored, int RowsFailed);
sealed record NormalizedSnapshot(
    int SchemaVersion,
    string Source,
    string GameVersion,
    string ExtractedAt,
    IReadOnlyList<NormalizedAsset> Assets,
    IReadOnlyList<NormalizedShop> Shops,
    IReadOnlyList<NormalizedOffer> Offers,
    IReadOnlyList<NormalizedOfferCost> Costs,
    IReadOnlyList<NormalizedOfferReward> Rewards,
    IReadOnlyList<NormalizedRequirement> Requirements,
    CoverageAudit Coverage
);

static class CurrencyResolver
{
    private static readonly IReadOnlyDictionary<uint, uint> CurrencyItems =
        new Dictionary<uint, uint>
        {
            [1] = 10309,
            [2] = 33913,
            [3] = 10311,
            [4] = 33914,
            [5] = 10307,
            [6] = 41784,
            [7] = 41785,
            [8] = 21072,
            [9] = 21073,
            [10] = 21074,
            [11] = 21075,
            [12] = 21076,
            [13] = 21077,
            [14] = 21078,
            [15] = 21079,
            [16] = 21080,
            [17] = 21081,
            [18] = 21172,
            [19] = 21173,
            [20] = 21935,
            [21] = 22525,
            [22] = 26533,
            [23] = 26807,
            [24] = 28063,
            [25] = 28186,
            [26] = 28187,
            [27] = 28188,
            [28] = 30341,
        };

    // Reproduces the conversion rules used by the locally installed AllaganLib build.
    // CostType is deliberately not used here: in this sheet it describes properties
    // such as HQ, while UseCurrencyType and a few shop IDs control placeholder IDs.
    public static uint Resolve(
        uint shopId,
        uint rawItemId,
        byte useCurrencyType,
        IReadOnlyDictionary<uint, uint>? tomestones
    )
    {
        if (shopId == 1770637 && CurrencyItems.TryGetValue(rawItemId, out var shopCurrency))
        {
            return shopCurrency;
        }

        if (
            shopId == 1770446
            || (shopId == 1770699 && rawItemId >= 10)
            || (shopId == 1770803 && rawItemId < 10)
        )
        {
            if (TryResolveTomestoneOrCurrency(rawItemId, tomestones, out var specialCurrency))
            {
                return specialCurrency;
            }
            return rawItemId;
        }

        var itemId = rawItemId;
        if (
            useCurrencyType == 16
            && rawItemId != 25
            && CurrencyItems.TryGetValue(rawItemId, out var mappedCurrency)
        )
        {
            itemId = mappedCurrency;
        }

        if (
            useCurrencyType == 2
            && rawItemId < 10
            && tomestones is not null
            && tomestones.TryGetValue(rawItemId, out var tomestoneItem)
        )
        {
            itemId = tomestoneItem;
        }

        if (
            shopId == 1770637
            && rawItemId < 10
            && CurrencyItems.TryGetValue(rawItemId, out var legacyCurrency)
        )
        {
            itemId = legacyCurrency;
        }

        if (
            (useCurrencyType == 16 || useCurrencyType == 4)
            && rawItemId < 10
            && shopId != 1770637
            && TryResolveTomestoneOrCurrency(rawItemId, tomestones, out var typedCurrency)
        )
        {
            itemId = typedCurrency;
        }

        return itemId;
    }

    public static object SelfTest()
    {
        IReadOnlyDictionary<uint, uint> tomestones = new Dictionary<uint, uint>
        {
            [1] = 28,
            [2] = 48,
        };
        var checks = new[]
        {
            new { name = "tomestone placeholder", actual = Resolve(1769533, 1, 2, tomestones), expected = 28u },
            new { name = "legacy currency placeholder", actual = Resolve(1769516, 5, 16, tomestones), expected = 10307u },
            new { name = "wolf mark exception", actual = Resolve(1769516, 25, 16, tomestones), expected = 25u },
            new { name = "special shop override", actual = Resolve(1770637, 2, 0, tomestones), expected = 33913u },
            new { name = "ordinary item cost", actual = Resolve(1769473, 4851, 2, tomestones), expected = 4851u },
        };
        return new
        {
            status = checks.All(check => check.actual == check.expected) ? "PASS" : "FAIL",
            checks,
        };
    }

    private static bool TryResolveTomestoneOrCurrency(
        uint rawItemId,
        IReadOnlyDictionary<uint, uint>? tomestones,
        out uint itemId
    )
    {
        if (tomestones is not null && tomestones.TryGetValue(rawItemId, out itemId))
        {
            return true;
        }
        return CurrencyItems.TryGetValue(rawItemId, out itemId);
    }
}
