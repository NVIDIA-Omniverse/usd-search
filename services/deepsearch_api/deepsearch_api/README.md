**USD Search API** enables developers, creators, and workflow specialists to efficiently search through vast collections of OpenUSD data, images, and other assets using natural language or image-based inputs.


With these production-ready microservices, developers can deploy USD Search API onto their own infrastructure. With USD Search API’s artificial intelligence (AI) features, you can quickly locate untagged and unstructured 3D data and digital assets, saving time navigating unstructured, untagged 3D data. USD Search API is capable of searching and indexing 3D asset databases, as well as navigating complex 3D scenes to perform spatial searches, without requiring manual tagging of assets.

## Features
- **Natural Language Searches:** - Utilize AI to search for images and USD-based 3D models using simple, descriptive language.
- **Image Similarity Searches:** - Find images similar to a reference image through AI-driven image comparisons.
- **Metadata Filtering:** - Filter search results by file name, file type, creation/modification dates, file size, and creator/modifier metadata.
- **USD Content Filtering with Asset Graph Search:** - When used with the Asset Graph Search, search capabilities are expanded to include filtering based on USD properties and object dimensions.
- **Multiple Storage Backend Support:** - Compatible with various storage backends, including AWS S3 buckets and Omniverse Nucleus server.
- **Advanced File Name, Extension, and Path Filters:** - Use wildcards for broad or specific file name and extension searches.
- **Date and Size Range Filtering:** - Specify assets created or modified within certain date ranges or file sizes larger or smaller than a designated threshold.
- **User-based Filtering:** - Filter assets based on their creator or modifier, allowing for searches tailored to particular users' contributions.
- **Embedding-based Similarity Threshold:** - Set a similarity threshold for more nuanced control over search results in embedding-based searches.
- **Custom Search Paths and Scenes:** - Specify search locations within the storage backend or conduct searches within specific scenes for targeted results.
- **Return Detailed Results:** - Option to include images, metadata, root prims, and predictions in the search results.

# Asset Graph Search (AGS) API Overview
**Asset Graph Search (AGS)** provides advanced querying capabilities for assets and USD trees indexed in a graph database. It supports proximity queries based on coordinates or prims to find objects within specified areas or radii, sorted by distance, and includes transformation options for vector alignment. The API also offers dependency and reverse dependency searches, helping to identify all assets referenced in a scene or scenes containing a particular asset, which can optimize scene loading and track dependency changes. By combining different query types, the AGS API enables complex scenarios for scene understanding, manipulation, and generation. Integrated with USD Search it provides in-scene search functionality.
## Features
- **Proximity Queries:** - Find objects within a specified bounding box or radius. - Results sorted by distance with options for vector alignment using a transformation matrix.
- **USD Property Queries:** - Enables querying objects in a 3D scene using USD properties, such as finding all assets with a specific semantic label.
- **Asset Dependency Searches:** - Identify all assets referenced in a scene — including USD references, material references, or textures. - Reverse search to find all scenes containing a particular asset.
- **Combined Query Capabilities:** - Enable complex scenarios for enhanced scene understanding, manipulation, and generation.
- **Integration with USD Search:** - Provides in-scene search functionality.
