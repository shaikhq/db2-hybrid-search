## Chapter 10. Large language model integration with Db2

In Db2, you can now register external watsonx.ai models directly within the database, enabling seamless integration of AI capabilities into your data workflows. To manage these external models, Db2 introduces new DDL statements to register models, remove them, and control usage privileges. By using the built-in TO\_EMBEDDING function, you can generate vector embeddings from text data, making it easier to do advanced analytics, such as semantic search or similarity comparisons. Furthermore, by using the built-in TEXT\_GENERATION function, you can generate text from a given prompt using a registered text generation model. Additionally, metadata can be tracked through the catalog views SYSCAT.EXTERNALMODELS, SYSCAT.EXTERNALMODELOPTIONS, and SYSCAT.EXTERNALMODELAUTH.

## Background and proposed solution

Db2 12.1.2 introduced support for a native VECTOR data type and a set of associated built-in functions. Db2 VECTOR data support enables customers to store and operate on VECTOR representations of their data directly within the database. However, before customers can leverage these new capabilities, they face a critical challenge: generating vector embeddings from their raw input data. Currently, customers must develop custom workflows or pipelines for vector generation, often relying on external APIs provided by cloud AI platforms. Some customers might also choose to use locally deployed language models through serving options. This fragmented and manual process introduces complexity, increases development time, and creates a barrier to adopting the new vector functionality in Db2.

The features included in this EAP release aim to address this gap by simplifying the integration of external language models with Db2. By allowing customers to register externally provisioned language models within Db2, they can invoke these models seamlessly through standard SQL queries. Raw input data can be sent to an external language model, and the resulting embeddings or generated text output can be retrieved, stored, and processed directly within Db2. This integration streamlines customer workflows, making it easier to incorporate external language model capabilities into language-driven applications, semantic search use cases, and other AI-powered solutions built on Db2.

This Early Access Program (EAP) release focuses on embedding generation and text generation . Included in this scope:

- Registering external embedding models.
- Dropping external models.
- Altering external models.
- Controlling access through GRANT and REVOKE statements.
- Generating embeddings using the TO\_EMBEDDING function.
- Generating text using the TEXT\_GENERATION function
- SYSCAT.EXTERNALMODELS, SYSCAT.EXTERNALMODELOPTIONS, and SYSCAT.EXTERNALMODELAUTH catalog views.

## CREATE EXTERNAL MODEL statement

The CREATE EXTERNAL MODEL statement registers an external AI model in Db2.

The model definition includes credentials and metadata for an external model, such as Watsonx.ai or OpenAI. By including this information in the definition, the model can be referenced by a logical name in builtin functions, such as TO\_EMBEDDING or TEXT\_GENERATION.

## Syntax

<!-- image -->

<!-- image -->

## text-generation-data-type

<!-- image -->

## Description

## model-name

Specifies the external model.

The name, including an implicit or explicit qualifier, must not identify an external model that already exists at the current server (SQLSTATE 42710). If a qualifier is not specified, the current schema is implicitly assigned. If the name is explicitly qualified with a schema name, the schema name must not begin with the characters "SYS" (SQLSTATE 42939).

## PROVIDER

Specifies the provider of the language model being used.

Db2 supports integration with various API providers for invoking language models by using REST APIs. Each supported API provider includes a REST API endpoint tailored to the specific model types it supports.

- WATSONX: When using the WATSONX provider, Db2 leverages the REST API specifications provided by watsonx.ai for model invocation.
- OPENAI: This provider option is for language models hosted in a private cloud environment. The OPENAI provider supports only REST APIs that are compatible with the OpenAI API specification.

## ID string-constant

Uniquely specifies the target model within the context of a given provider. Different providers may use the same model ID to refer to similar or identical models, but the ID must be unique within each provider's model catalog. Db2 uses the ID to locate and interact with the correct remote model during API calls. The value must match the identifier published in the provider's documentation or model registry. If the model ID does not correspond to the expected value, integration and invocation fails.

The string-constant value must not be an empty string, and must not exceed 256 bytes in length (SQLSTATE 42615).

## URL string-constant

Specifies the HTTPS endpoint of the watsonx embedding API.

This endpoint must be a valid and accessible HTTPS URL that points to the embedding service interface of the model. Db2 uses this URL to issue API requests for model invocation. If watsonx supplies only a base URL and expects the client to construct the full endpoint dynamically, Db2 assembles the complete URL according to the documented conventions of the watsonx API. The final URL must conform to the watsonx expected request structure and support the required authentication mechanisms.

The string-constant value must not exceed 512 bytes in length (SQLSTATE 42622).

Specifies the HTTPS endpoint of the external model provided by the model provider.

This endpoint must be a valid and accessible HTTPS URL that points to the model's inference or service interface. Db2 uses this URL to issue API requests for model invocation. If the provider supplies only a base URL and expects the client to construct the full endpoint dynamically, Db2 will automatically assemble the complete URL according to the provider's documented conventions. The final URL must conform to the provider's expected request structure and support the required

authentication mechanisms.

The string-constant value value must not be an empty string, and must not exceed 256 bytes in length (SQLSTATE 42615).

## PROJECT\_ID string-constant

Specifies the project identifier for API usage, billing, and access control.

This value must follow platform naming rules and be unique within the account.

The string-constant value must not exceed 256 bytes in length (SQLSTATE 42622).

## SPACE\_ID string-constant

Specifies the space identifier for API usage, billing, and access control.

This value must follow platform naming rules and be unique within the account.

The string-constant value must not exceed 256 bytes in length (SQLSTATE 42622).

## KEY string-constant

Provides the authentication token or API key required to access the provider's model endpoint.

This key is used to authorize requests made from Db2 to the external provider. The key must be valid, active, and have the necessary permissions to invoke the specified model. The key is typically issued by the provider and can be subject to expiration or usage limits.

The string-constant value must not exceed 512 bytes in length (SQLSTATE 42622).

## model-type

Defines the functional category of the external model being registered. This parameter informs Db2 of the model's intended purpose and determines how it will be integrated and invoked within SQL operations.

The supported model types are:

## TEXT\_EMBEDDING

Indicates that the model transforms input text into high-dimensional vector embeddings, which can be used for tasks such as semantic similarity, clustering, or vector-based search. This type of model is used in the TO\_EMBEDDING builtin function.

## dimension

An integer constant that specifies the dimension of the vector. For a row-organized table, the value must be from 1 to 8168 for FLOAT32 and from 1 to 32672 for INT8 (SQLSTATE 42611). For a column-organized table, the value must be from 1 to 8148 for FLOAT32 and from 1 to 32592 for INT8 (SQLSTATE 42611).

## coordinate-type

- REAL or FLOAT32: single-precision, 4-byte floating point.
- INT8: 1-byte integer.

## TEXT\_GENERATION

This type of model generates text based on an input prompt. This model type is used in the TEXT\_GENERATION builtin function.

## watsonx-text-generation-options

These options can only be specified for provider WATSONX with model type TEXT\_GENERATION (SQLSTATE 42601).

## MAX\_NEW\_TOKENS integer-constant

Specifies the maximum number of tokens the text generation model can generate. Controls output length and resource usage. The integer-constant value must be greater than or equal to 0 (SQLSTATE 42615)

## MIN\_NEW\_TOKENS integer-constant

Specifies the minimum number of tokens the text generation model can generate. Controls output length and resource usage. The integer-constant value must be greater than or equal to 0 (SQLSTATE 42615).

## RANDOM\_SEED integer-constant

Random number generator seed to use in sampling mode for experimental repeatability. The integer-constant value must be greater than 0 (SQLSTATE 42615).

## REPETITION\_PENALTY numeric-constant

Represents the penalty for penalizing tokens that have already been generated or belong to the context. The value 1.0 means that there is no penalty. The numeric-constant value must be between 1.0 and 2.0 inclusive (SQLSTATE 42615).

## STOP\_SEQUENCE1 to STOP\_SEQUENCE4 string\_constant

Up to four strings which will cause the text generation to stop if or when any are produced as part of the output. Stop sequences encountered prior to the minimum number of tokens being generated will be ignored. The string-constant value must not be an empty string, and must not exceed 256 bytes in length (SQLSTATE 42615).

## TEMPERATURE numeric-constant

Used to modify the next-token probabilities in sampling mode. Values less than 1.0 sharpen the probability distribution, producing a more deterministic output. Values greater than 1.0 flatten the probability distribution, producing a more varied output. A value of 1.0 has no effect. The numeric-constant value must be between 0.05 and 2.0 inclusive (SQLSTATE 42615).

## TIME\_LIMIT integer-constant

Time limit in milliseconds. If text generation is not completed within the time limit, the generation will stop. The text generated within the time limit is returned along with the TIME\_LIMIT stop reason. Depending on the plan with the provider and on the model being used, an enforced time limit may be in place. The integer-constant value must be greater than 0 (SQLSTATE 42615).

## TRUNCATE\_INPUT\_TOKENS integer-constant

Specifies the maximum number of input tokens allowed. Use this setting to prevent requests from failing when the input is longer than the configured limits. If truncation occurs, tokens are removed from the start of the input and the end of the input remains intact. If this value is greater than the model's maximum sequence length, the request fails when the total token count exceeds that maximum. To find the model's maximum sequence length, refer to the specific model's documentation. The integer-constant value must be greater than 0 (SQLSTATE 42615).

## openai-text-generation-options

## These options can only be specified for provider OPENAI with model type TEXT\_GENERATION (SQLSTATE 42601).

## FREQUENCY\_PENALTY numeric-constant

The numeric-constant value must be between -2.0 and 2.0 inclusive (SQLSTATE 42615).

## Notes

- The owner of the external model is granted ALTER and USAGE privileges on the model. The owner of the model can drop the model.
- There is no validation of credentials or other settings when creating a model. To validate the settings, invoke the appropriate builtin function such as TO\_EMBEDDING or TEXT\_GENERATION.

## watsonx.ai example

```
CREATE EXTERNAL MODEL aschema.granite-embed PROVIDER WATSONX KEY 'api-keyxxxxx' ID 'ibm/slate-30m-english-rtrvr' TYPE TEXT_EMBEDDING RETURNING VECTOR(1024, FLOAT32) URL 'https://us-south.ml.cloud.ibm.com/ml/v1/text/embeddings' PROJECT_ID 'f5599cfd-7aca-451e-b897-35d8f624e775'
```

## ALTER EXTERNAL MODEL statement

The ALTER EXTERNAL MODEL statement updates, adds, or drops a metadata attribute in an existing external model.

## Invocation

This statement can be embedded in an application program or issued through the use of dynamic SQL statements. It is an executable statement that can be dynamically prepared only if DYNAMICRULES run behavior is in effect for the package (SQLSTATE 42509).

## Authorization

The privileges held by the authorization ID of the statement must include at least one of the following authorities:

- ALTER privilege on the external model to be altered.
- ALTERIN privilege on the schema of the external model.
- SCHEMAADM authority on the schema of the external model.
- DBADM authority

## MAX\_COMPLETION\_TOKENS integer-constant

The integer-constant value must be greater than or equal to 0 (SQLSTATE 42615).

## REASONING\_EFFORT

Constrains effort on reasoning. Supported values are MINIMAL, LOW, MEDIUM, and HIGH. Reducing reasoning effort can result in faster responses and fewer tokens used on reasoning in a response.

## STOP1 to STOP4 string\_constant

Up to four strings which cause the text generation to stop if any are produced as part of the output. The string-constant value must not be an empty string, and must not exceed 256 bytes in length (SQLSTATE 42615).

## TEMPERATURE numeric-constant

The numeric-constant value must be between 0.00 and 2.0 inclusive (SQLSTATE 42615).

## Syntax

<!-- image -->

<!-- image -->

<!-- image -->

## openai-text-options

<!-- image -->

## Description

## model-name

Identifies the name of the external model whose configuration is being altered. This name must correspond to a model registered in the catalog (SQLSTATE 42704).

## ID string-constant

Uniquely specifies the target model within the context of a given provider. Different providers may use the same model ID to refer to similar or identical models, but the ID must be unique within each provider's model catalog. Db2 uses the ID to locate and interact with the correct remote model during API calls. The value must match the identifier published in the provider's documentation or model registry. If the model ID does not correspond to the expected value, integration and invocation fails.

## return-type

Defines the return type of the model. The model type cannot be altered and the specified return type must agree with the model type specified during external model creation. (SQLSTATE 42601).

## URL string-constant

Defines the HTTPS endpoint of the external model as provided by the model provider. This endpoint must be a valid and accessible HTTPS URL that points to the model's inference or service interface. Db2 uses this URL to issue API requests for model invocation. If the provider supplies only a base URL and expects the client to construct the full endpoint dynamically, Db2 will automatically assemble the complete URL according to the provider's documented conventions. The final URL must conform to the provider's expected request structure and support the required authentication mechanisms.

string-constant must not be an empty string, and must not exceed 512 bytes in length (SQLSTATE 42615).

## KEY string-constant

Provides the authentication token or API key required to access the provider's model endpoint. This key is used to authorize requests made from Db2 to the external provider. It must be valid and active, and it should have the necessary permissions to invoke the specified model. The key is typically issued by the provider and may be subject to expiration or usage limits. The string-constant value must not be an empty string, and must not exceed 512 bytes in length (SQLSTATE 42615).

## PROJECT\_ID string-constant

Specifies the project identifier for API usage, billing, and access control. Must follow platform naming rules and be unique within the account. The string-constant value must not be an empty string, and must not exceed 256 bytes in length (SQLSTATE 42615).

## watsonx-text-generation-options

These options can only be specified for provider WATSONX with model type TEXT\_GENERATION (SQLSTATE 42601). See CREATE EXTERNAL MODEL for more information.

## openai-text-generation-options

These options can only be specified for provider OPENAI with model type TEXT\_GENERATION (SQLSTATE 42601). See CREATE EXTERNAL MODEL for more information.

## Rules

- At least one SET or DROP clause is required (SQLSTATE 42601).
- A parameter cannot be set and dropped within a single invocation (SQLSTATE 42613).
- If the model provider is WATSONX:
- KEY cannot be dropped (SQLSTATE 42601).
- Either PROJECT\_ID or SPACE\_ID must be defined for a given external model, and they cannot both be defined (SQLSTATE 42613). For example, if a model currently has PROJECT\_ID defined, and DROP PROJECT\_ID is specified, then SET SPACE\_ID must also be specified in the same invocation.
- If the model provider is OPENAI, then PROJECT\_ID and SPACE\_ID cannot be set.

## Example

```
ALTER EXTERNAL MODEL aschema.granite-embed SET KEY 'api-keyxxxxx' SET PROJECT_ID 'MY-PROJECT-ID'
```

## DROP EXTERNAL MODEL statement

The DROP EXTERNAL MODEL statement removes an external model definition from the catalog. Once dropped, the model can no longer be referenced in SQL statements or built-in functions such as TO\_EMBEDDING.

## Syntax

<!-- image -->

## Description

## model-name

Specifies the external model to be dropped

The model-name value must identify an external model that is described in the catalog (SQLSTATE 42704).

## RESTRICT

Prevents the external model from being dropped if it is referenced in an SQL routine definition, trigger definition, or view definition (SQLSTATE 42893).

The restrict rule is enforced by default if the following conditions are met:

- The auto\_reval database configuration parameter is set to disabled.
- An inline trigger definition, inline SQL function definition, inline SQL method definition, or view references the variable.

## Example

Note: The parameter values in the following example, such as model name, ID, URL, Key, project ID, are placeholders. Replace them with the actual values required in your environment.

The following example shows the command syntax for dropping an external model created with a name MYMODEL:

DROP EXTERNAL MODEL MYSCHEMA.MYMODEL;

## TRANSFER OWNERSHIP statement

The TRANSFER OWNERSHIP statement transfers ownership of a database object.

## Syntax

<!-- image -->

## Description

## EXTERNAL MODEL model-name

Identifies the external model that is to have its ownership transferred. The model-name must identify an external model that is described in the catalog (SQLSTATE 42704). When ownership of the external model is transferred, the value in the OWNER column for the external model in the SYSCAT.EXTERNALMODELS catalog view is replaced with the authorization ID of the new owner.

## GRANT (external model privileges)

This form of the GRANT statement grants the USAGE privilege on an external model

<!-- image -->

## Description

## ALL|ALL PRIVILEGES

Grants all privileges on the specified external model.

## USAGE

Grants the privilege to use an external model. A user must have the USAGE privilege on a model to invoke it for tasks such as inference or embedding generation.

## ALTER

Grants the privilege to alter existing external model by using the ALTER EXTERNAL MODEL statement.

## ON EXTERNAL MODEL model-name

Identifies the external model on which one or more privileges are to be granted. The model-name value, including an implicit or explicit qualifier, must identify an external model that exists at the current server (SQLSTATE 42704).

## TO

Specifies the recipients of the specified privilege.

## USER

Specifies that the authorization-name identifies a user.

## GROUP

Specifies that the authorization-name identifies a group.

## ROLE

Specifies that the authorization-name identifies an existing role at the current server (SQLSTATE 42704).

## authorization-name,...

Lists the authorization IDs of one or more users, groups, or roles. The list of authorization IDs cannot include the authorization ID of the user issuing the statement (SQLSTATE 42502).

## PUBLIC

Grants the privilege to all users (authorization IDs) in the system.

<!-- image -->

## Example

Note: The parameter values in the following example are placeholders. Replace them with the actual values required in your environment.

The following example shows the command syntax for granting the user LISA the ability to use the external model aschema.granite-embed :

GRANT USAGE ON EXTERNAL MODEL aschema.granite-embed TO USER LISA

## REVOKE (external model privileges)

This form of the REVOKE statement revokes the USAGE privilege from an external model.

## Syntax

<!-- image -->

## Description

## ALL|ALL PRIVILEGES

Revokes all privileges to use the specified external model.

## USAGE

Revokes the privilege to use an external model. Once the USAGE privilege is revoked, the specified user, group, or role can no longer invoke the model for tasks, such as generating embeddings or text.

## ALTER

Revokes the privilege to modify the properties of external model by using the ALTER EXTERNAL MODEL statement.

## ON EXTERNAL MODEL model-name

Specifies the external model from which the specified privilege is to be revoked. The model-name must refer to a model that exists and is registered in the model catalog. If the model does not exist, the statement fails with an appropriate error.

## FROM

Specifies from whom the specified privilege is revoked.

## USER

Specifies that the authorization-name identifies a user.

## GROUP

Specifies that the authorization-name identifies a group.

## ROLE

Specifies that the authorization-name identifies an existing role at the current server (SQLSTATE 42704).

## authorization-name,...

Lists the authorization IDs of one or more users, groups, or roles. The list of authorization IDs cannot include the authorization ID of the user issuing the statement (SQLSTATE 42502).

## PUBLIC

Specifies all users (authorization IDs) in the system.

## BY ALL

Specifies all named users who were explicitly granted named privileges, regardless of who granted them. This is the default behavior.

## Rules

For each authorization-name specified without USER, GROUP, nor ROLE specified, the database determines the type based on entries in the SYSCAT.EXTERNALMODELAUTH catalog view. For all rows for the specified object where the grantee matches the authorization-name:

- If all rows have a GRANTEETYPE value of 'U', the authorization-name is treated as a USER.
- If all rows have a GRANTEETYPE value of 'G', the authorization-name is treated as a GROUP.
- If all rows have a GRANTEETYPE value of 'R', the authorization-name is treated as a ROLE.
- If the rows do not all have the same GRANTEETYPE value, an error is returned (SQLSTATE 56092).

## Notes

- If you revoke a privilege on an external model from the authorization ID that bound a package, the package becomes invalid unless that authorization ID still holds the privilege on the sequence through another source, such as membership in a role that holds the privilege.
- Revoking a specific privilege does not always prevent a user from performing the related action. A user can still perform the action if they hold other privileges through PUBLIC, through a group they belong to, or through a higher level of authority such as DBADM.

## Example

Note: The parameter values in the following example are placeholders. Replace them with the actual values required in your environment.

The following example shows the command syntax for revoking the ability to use the external model aschema.granite-embed from the user LISA:

REVOKE USAGE ON EXTERNAL MODEL aschema.granite-embed FROM USER LISA

## TO\_EMBEDDING

The TO\_EMBEDDING built-in function returns the embedding vector for an input string.

```
TO_EMBEDDING ( string-expression USING model-name )
```

The schema is SYSIBM.

## string-expression

A `VARCHAR` value containing the text to be embedded.

## model-name

A registered embedding model to be used for generating an embedding vector. USAGE privilege is required on the external model.

The result of the function is a VECTOR type value with the dimension and coordinate-type specified in model-name . If the first argument can be null, the result can be null. If the first argument is null, the result is the null value.

The following example shows the command syntax for returning an embedded vector by using the external model model1 :

```
db2 "VALUES TO_EMBEDDING('hello embedding' USING db2inst1.model1)"
```

## TEXT\_GENERATION

The TEXT\_GENERATION built-in function returns the generated text based on an input string. TEXT\_GENERATION is a non-deterministic function.

```
TEXT_GENERATION ( string-expression USING model-name )
```

The schema is SYSIBM.

## string-expression

A string value representing the prompt from which to generate text.

## model-name

A registered text generation model to be use for text generation. In dynamic SQL statements, the CURRENT SCHEMA special register is used as a qualifier for an unqualified external model name. In static SQL statements, the QUALIFIER precompile or bind option implicitly specifies the qualifier for an unqualified external model name. The external model must be defined with model type TEXT\_GENERATION (SQLSTATE 42858).

The result of the function is a string type as defined in model-name. If the first argument can be null, the result can be null. If the first argument is null, the result is the null value.

## Notes

- The privileges held by the authorization ID of the statement must include at least one of the following privileges:
- The USAGE privilege on the external model.
- DATAACCESS authority.

## SQL messages and states

The following are new SQL and SQLSTATE messages.

## SQL messages

| Table 2. SQL messages   | Table 2. SQL messages                                                                                                                  | Table 2. SQL messages                                                                                                                                                                                                                              | Table 2. SQL messages                                                                                                                                                                                                                                                                                                                                 |
|-------------------------|----------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| SQL Message ID          | Message                                                                                                                                | Explanation                                                                                                                                                                                                                                        | User Response                                                                                                                                                                                                                                                                                                                                         |
| SQL20592N               | The statement was not processed because an AI API from provider returned an error: <error-msg> . See db2diag.log for more information. | The external AI API returned an error. indicates the provider of the API. And is a snippet of the error message returned from the API. The entire error message is logged in db2diag.log.                                                          | Determine what is incorrect by reviewing the error message snippet or detailed error message in the db2diag.log. Ensure the following prerequisites are met: • You are using a valid external model. • You are using valid API credentials, model fields and options depending on the operation and provider. • You are using a supported input type. |
| SQL20593N               | The statement was not processed because connection to an AI API with provider <provider-name> was unsuccessful.                        | Db2 could not make a connection to AI API. <provider> indicate provider of the API.                                                                                                                                                                | Determine what is incorrect about the external model: • Validate external model. • Validate API credentials, model fields and options depending on the operation and provider                                                                                                                                                                         |
| SQL20595N               | The external model <model name> that is specified for built- in function <function name> is defined with an incompatible model type.   | The built-in function requires an external model that is defined with a compatible model type: TO_EMBEDDING Requires an external model with model type TEXT_EMBEDDING. TEXT_GENERATION Requires an external model with model type TEXT_GENERATION. | Specify an external model with a compatible model type.                                                                                                                                                                                                                                                                                               |

## SQLSTATE messages

| Table 3. SQLSTATE messages   | Table 3. SQLSTATE messages                  |
|------------------------------|---------------------------------------------|
| SQLSTATE value               | Meaning                                     |
| 38555                        | Error from external AI API.                 |
| 38556                        | Unsuccessful connection to external AI API. |

## Catalog views

The catalog view SYSCAT.EXTERNALMODELS is defined to provide metadata about externally defined machine learning models that are integrated into the database system via the CREATE EXTERNAL MODEL statement. This view captures essential information about the external model's identity, provider, access configuration, and user-defined options.

| Table 4. SYSCAT.EXTERNALMODELS catalog view   | Table 4. SYSCAT.EXTERNALMODELS catalog view   | Table 4. SYSCAT.EXTERNALMODELS catalog view   | Table 4. SYSCAT.EXTERNALMODELS catalog view                          |
|-----------------------------------------------|-----------------------------------------------|-----------------------------------------------|----------------------------------------------------------------------|
| Column Name                                   | Data Type                                     | Nullable                                      | Description                                                          |
| MODELSCHEMA                                   | VARCHAR(128)                                  | No                                            | Schema name of the external model.                                   |
| MODELNAME                                     | VARCHAR(128)                                  | No                                            | Unqualified name of the external model.                              |
| PROVIDER                                      | VARCHAR(128)                                  | No                                            | External model provider, e.g. WATSONX or OPENAI.                     |
| MODELID                                       | VARCHAR(256)                                  | No                                            | Unique identifier of the model within the provider's system.         |
| MODELTYPE                                     | VARCHAR(32)                                   | No                                            | Type of the model, for example: • TEXT_EMBEDDING • TEXT_GENERATION   |
| RETURNTYPE                                    | VARCHAR(128)                                  | No                                            | Return type of the external model, for example: VECTOR(768,FLOAT32). |
| URL                                           | VARCHAR(512)                                  | No                                            | URL endpoint used to invoke the external model.                      |
| OWNER                                         | VARCHAR(128)                                  | No                                            | Authorization ID of the owner of the external model.                 |
| OWNERTYPE                                     | VARCHAR(1)                                    | No                                            | • S = The owner is the system • U = The owner is an individual user. |

| Table 5. SYSCAT.EXTERNALMODELOPTIONS Catalog View   | Table 5. SYSCAT.EXTERNALMODELOPTIONS Catalog View   | Table 5. SYSCAT.EXTERNALMODELOPTIONS Catalog View   | Table 5. SYSCAT.EXTERNALMODELOPTIONS Catalog View   |
|-----------------------------------------------------|-----------------------------------------------------|-----------------------------------------------------|-----------------------------------------------------|
| Column Name                                         | Data Type                                           | Nullable                                            | Description                                         |
| MODELSCHEMA                                         | VARCHAR(128)                                        | No                                                  | Schema of the external model.                       |
| MODELNAME                                           | VARCHAR(128)                                        | No                                                  | Unqualified name of the external model.             |
| OPTION                                              | VARCHAR(128)                                        | No                                                  | Name of the external model option.                  |
| SETTING                                             | VARCHAR(256)                                        | No                                                  | Value of the external model option.                 |

| Table 6. SYSCAT.EXTERNALMODELAUTH catalog view   | Table 6. SYSCAT.EXTERNALMODELAUTH catalog view   | Table 6. SYSCAT.EXTERNALMODELAUTH catalog view   | Table 6. SYSCAT.EXTERNALMODELAUTH catalog view                                   |
|--------------------------------------------------|--------------------------------------------------|--------------------------------------------------|----------------------------------------------------------------------------------|
| Column Name                                      | Data Type                                        | Nullable                                         | Description                                                                      |
| GRANTOR                                          | VARCHAR(128)                                     | No                                               | Grantor of a privilege.                                                          |
| GRANTEE                                          | CHAR(1)                                          | No                                               | Indicates type of grantor: • S = System • U = User                               |
| GRANTEE                                          | VARCHAR(128)                                     | No                                               | Holder of a privilege                                                            |
| GRANTEETYPE                                      | CHAR(1)                                          | No                                               | Type of grantee: • G = Group • R = Role • U = Individual user                    |
| MODELSCHEMA                                      | VARCHAR(128)                                     | No                                               | Schema name of the external model to which this privilege applies.               |
| MODELNAME                                        | VARCHAR(128)                                     | No                                               | Unqualified name of the external model to which this privilege applies.          |
| ALTERAUTH                                        | CHAR(1)                                          | No                                               | Privilege to alter the model: • G = Held and grantable • Y = Held • N = Not held |
| USAGEAUTH                                        | CHAR(1)                                          | No                                               | Privilege to use the model: • G = Held and grantable • Y = Held • N = Not held   |

| Table 6. SYSCAT.EXTERNALMODELAUTH catalog view (continued)   | Table 6. SYSCAT.EXTERNALMODELAUTH catalog view (continued)   | Table 6. SYSCAT.EXTERNALMODELAUTH catalog view (continued)   | Table 6. SYSCAT.EXTERNALMODELAUTH catalog view (continued)   |
|--------------------------------------------------------------|--------------------------------------------------------------|--------------------------------------------------------------|--------------------------------------------------------------|
| Column Name                                                  | Data Type                                                    | Nullable                                                     | Description                                                  |
| GRANT_TIME                                                   | TIMESTAMP                                                    | No                                                           | Time at which the privilege was granted.                     |
| GRANTREVOKE_TIME                                             | TIMESTAMP                                                    | No                                                           | Time at which the privilege was last granted or revoked.     |

## Dependency tracking for external models

The BTYPE value of '9' is introduced in the system dependence catalog view to enable dependency between database objects and external models.

This feature allows the system to track when objects such as routines or triggers refer to an external model, ensuring proper invalidation or impact analysis if the model is modified or dropped.

The following catalog views will be updated to support BTYPE = '9' for external model dependencies:

- SYSCAT.CONTROLDEP
- SYSCAT.PACKAGEDEP
- SYSCAT.ROUTINEDEP
- SYSCAT.TABDEP
- SYSCAT.TRIGDEP
- SYSCAT.VARIABLEDEP

All affected catalog views will record BTYPE = '9' in their respective BTYPE columns when the dependency involves an external model.